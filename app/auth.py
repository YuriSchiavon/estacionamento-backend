"""
Login por usuário e senha. Cada conta (pessoa ou totem) pertence a um
papel e, exceto "dono", a uma unidade específica -- ver app/models.py
Usuario e PapelUsuario.

Token de sessão é opaco (não é JWT): revogar é só apagar a linha em
`Sessao`, sem precisar de lista de bloqueio nem gestão de chave de
assinatura.
"""
import secrets
import unicodedata
from datetime import timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from typing import List

from . import models, schemas
from .database import get_db
from .security import unidades_selecionaveis, usuario_logado
from .tempo import agora_utc

DURACAO_SESSAO_HORAS = 24
# Totens ficam logados uma vez, no equipamento, presumivelmente pra sempre
# (é o que as próprias telas de totem prometem: "faça login uma vez, fica
# salvo neste equipamento"). Sessão de 24h faria todo totem parar de
# funcionar sozinho todo dia até alguém notar e logar de novo na mão --
# inviável pra um equipamento desassistido rodando 24/7. 90 dias dá uma
# folga grande sem ser "para sempre" (facilita revogar girando a senha
# periodicamente, se algum dia quiser).
DURACAO_SESSAO_TOTEM_HORAS = 24 * 90
PAPEIS_TOTEM = (
    models.PapelUsuario.totem_entrada,
    models.PapelUsuario.totem_validacao,
    models.PapelUsuario.totem_saida,
)

router = APIRouter()


def gerar_hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def conferir_senha(senha: str, senha_hash: str) -> bool:
    return bcrypt.checkpw(senha.encode(), senha_hash.encode())


def slugify(texto: str) -> str:
    """Username tem que ser seguro de digitar/configurar em qualquer
    equipamento -- sem acento, sem espaço, só ascii minúsculo."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    letras = [c.lower() if c.isalnum() and c.isascii() else "-" for c in sem_acento]
    slug = "".join(letras).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "unidade"


def gerar_senha_temporaria() -> str:
    return secrets.token_urlsafe(9)


def criar_usuario(
    db: Session,
    username: str,
    senha: str,
    nome: str,
    papel: "models.PapelUsuario",
    unidade_id: int | None = None,
    pode_liberar_manualmente: bool = False,
) -> models.Usuario:
    usuario = models.Usuario(
        username=username,
        senha_hash=gerar_hash_senha(senha),
        nome=nome,
        papel=papel,
        unidade_id=unidade_id,
        pode_liberar_manualmente=pode_liberar_manualmente,
    )
    db.add(usuario)
    db.flush()
    return usuario


def username_disponivel(db: Session, username: str) -> str:
    """Se já existir, sufixa com número até achar um username livre."""
    candidato = username
    sufixo = 2
    while db.query(models.Usuario).filter_by(username=candidato).first():
        candidato = f"{username}-{sufixo}"
        sufixo += 1
    return candidato


def criar_sessao(db: Session, usuario: models.Usuario) -> models.Sessao:
    duracao = DURACAO_SESSAO_TOTEM_HORAS if usuario.papel in PAPEIS_TOTEM else DURACAO_SESSAO_HORAS
    sessao = models.Sessao(
        usuario_id=usuario.id,
        token=secrets.token_hex(32),
        expira_em=agora_utc() + timedelta(hours=duracao),
    )
    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


@router.post("/auth/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(models.Usuario).filter_by(username=payload.username, ativo=True).first()
    if not usuario or not conferir_senha(payload.senha, usuario.senha_hash):
        raise HTTPException(401, "Usuário ou senha inválidos")

    sessao = criar_sessao(db, usuario)
    return schemas.LoginResponse(
        token=sessao.token,
        papel=usuario.papel,
        unidade_id=usuario.unidade_id,
        nome=usuario.nome,
        pode_liberar_manualmente=usuario.pode_liberar_manualmente,
    )


@router.post("/auth/logout")
def logout(payload: schemas.LogoutRequest, db: Session = Depends(get_db)):
    db.query(models.Sessao).filter_by(token=payload.token).delete()
    db.commit()
    return {"detail": "Sessão encerrada"}


@router.get("/auth/minhas-unidades", response_model=List[schemas.UnidadeSelecionavelOut])
def minhas_unidades(db: Session = Depends(get_db), usuario: models.Usuario = Depends(usuario_logado)):
    """Lista de unidades que a conta logada pode escolher operar na tela de
    Operação -- todas, se dono/gerente de operações; a própria + as extras
    autorizadas, se for uma conta com unidade fixa (ver
    security.unidades_selecionaveis). Sem restrição de papel: qualquer
    conta logada pode consultar a própria lista."""
    return unidades_selecionaveis(db, usuario)


@router.post("/auth/trocar-senha")
def trocar_senha(
    payload: schemas.TrocarSenhaRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(usuario_logado),
):
    """Autoatendimento -- qualquer conta logada troca a própria senha,
    desde que confirme a senha atual. Não depende de nenhum papel."""
    if not conferir_senha(payload.senha_atual, usuario.senha_hash):
        raise HTTPException(401, "Senha atual incorreta")
    if len(payload.nova_senha) < 6:
        raise HTTPException(422, "A nova senha deve ter pelo menos 6 caracteres")

    usuario.senha_hash = gerar_hash_senha(payload.nova_senha)
    db.commit()
    return {"detail": "Senha alterada com sucesso"}
