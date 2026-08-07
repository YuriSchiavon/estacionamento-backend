"""
Autenticação por login (usuário/senha), não mais por chave de API fixa.

Cada requisição autenticada manda `Authorization: Bearer <token>`, obtido
via POST /auth/login (ver app/auth.py). O token é opaco e fica guardado
em `Sessao` -- revogar é só apagar a linha, sem precisar de blocklist.

As dependências abaixo são definidas como objetos de módulo (não fábricas
chamadas inline nas rotas) de propósito: assim os testes conseguem fazer
`app.dependency_overrides[exigir_totem_entrada] = ...` apontando pro
mesmo objeto usado nas rotas -- se cada rota chamasse a fábrica na hora,
cada uma criaria uma função diferente e o override não bateria em todas.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .tempo import agora_utc


def usuario_logado(
    authorization: Optional[str] = Header(default=None), db: Session = Depends(get_db)
) -> models.Usuario:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login para continuar")

    token = authorization.removeprefix("Bearer ").strip()
    sessao = db.query(models.Sessao).filter_by(token=token).first()
    if not sessao or sessao.expira_em < agora_utc():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida ou expirada, faça login novamente")

    usuario = sessao.usuario
    if not usuario or not usuario.ativo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário inativo")
    return usuario


def _exigir_papel(*papeis_permitidos: models.PapelUsuario):
    def dependencia(usuario: models.Usuario = Depends(usuario_logado)) -> models.Usuario:
        if usuario.papel not in papeis_permitidos:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Seu usuário não tem permissão para essa ação")
        return usuario
    return dependencia


# Dependências nomeadas em nível de módulo -- ver docstring do arquivo
# sobre por que isso importa pros overrides de teste.
exigir_totem_entrada = _exigir_papel(models.PapelUsuario.totem_entrada)
exigir_totem_validacao = _exigir_papel(models.PapelUsuario.totem_validacao)
exigir_totem_saida = _exigir_papel(models.PapelUsuario.totem_saida)
exigir_gestao = _exigir_papel(models.PapelUsuario.dono, models.PapelUsuario.gerente)


def exigir_liberacao_manual(usuario: models.Usuario = Depends(exigir_gestao)) -> models.Usuario:
    """Permissão elevada e independente do papel -- só quem tem a flag
    pode_liberar_manualmente consegue abrir cancela na mão ou limpar pátio,
    mesmo sendo dono/gerente."""
    if not usuario.pode_liberar_manualmente:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Seu usuário não tem permissão para liberação manual/limpeza de pátio",
        )
    return usuario


def escopo_unidade(usuario: models.Usuario, unidade_id_query: Optional[int]) -> Optional[int]:
    """Resolve qual unidade uma consulta de relatório deve enxergar.

    Gerente nunca sai da própria unidade -- ignora qualquer valor vindo do
    cliente, nunca confia em tenant id informado por quem já está preso a
    uma unidade. Dono pode filtrar por uma unidade específica ou ver tudo
    (retorno None = "geral", agrega todas as unidades)."""
    if usuario.papel == models.PapelUsuario.dono:
        return unidade_id_query
    return usuario.unidade_id
