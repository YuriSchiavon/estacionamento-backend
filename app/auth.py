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

from . import models, schemas
from .database import get_db
from .tempo import agora_utc

DURACAO_SESSAO_HORAS = 24

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
    sessao = models.Sessao(
        usuario_id=usuario.id,
        token=secrets.token_hex(32),
        expira_em=agora_utc() + timedelta(hours=DURACAO_SESSAO_HORAS),
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
