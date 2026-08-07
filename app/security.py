"""
Autenticação por chave de API fixa, uma por totem físico.

Cada endpoint só aceita a chave do totem responsável por ele (ver mapeamento
em app/main.py) -- assim, se a chave de um totem vazar ou o equipamento for
trocado, dá pra revogar/trocar só aquela chave sem afetar os outros totens.

Sem as variáveis de ambiente configuradas, cada totem cai num valor padrão
de desenvolvimento (só pra não travar o ambiente local/demo) -- troque todas
elas no .env antes de ir para produção. Ver .env.example.
"""
import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

_CHAVES_PADRAO_DEV = {
    "entrada": ("API_KEY_ENTRADA", "dev-entrada-troque-em-producao"),
    "validação": ("API_KEY_VALIDACAO", "dev-validacao-troque-em-producao"),
    "saída": ("API_KEY_SAIDA", "dev-saida-troque-em-producao"),
    "gestão": ("API_KEY_GESTAO", "dev-gestao-troque-em-producao"),
    "liberação manual": ("API_KEY_LIBERACAO_MANUAL", "dev-liberacao-manual-troque-em-producao"),
}


def _chave_configurada(totem: str) -> str:
    nome_env, padrao_dev = _CHAVES_PADRAO_DEV[totem]
    return os.environ.get(nome_env, padrao_dev)


def _validar(totem: str, x_api_key: Optional[str]) -> None:
    chave_esperada = _chave_configurada(totem)
    if not x_api_key or not secrets.compare_digest(x_api_key, chave_esperada):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"Chave de API do totem de {totem} inválida ou ausente",
        )


def exigir_chave_entrada(x_api_key: Optional[str] = Header(default=None)):
    _validar("entrada", x_api_key)


def exigir_chave_validacao(x_api_key: Optional[str] = Header(default=None)):
    _validar("validação", x_api_key)


def exigir_chave_saida(x_api_key: Optional[str] = Header(default=None)):
    _validar("saída", x_api_key)


def exigir_chave_gestao(x_api_key: Optional[str] = Header(default=None)):
    """Chave do painel de gestão -- não deve ser configurada em nenhum totem."""
    _validar("gestão", x_api_key)


def exigir_chave_liberacao_manual(x_api_key: Optional[str] = Header(default=None)):
    """Chave própria e mais restrita, separada da chave geral de gestão --
    só quem tem essa chave consegue abrir cancela manualmente. Quem só
    consulta relatórios (chave de gestão) não consegue acionar isso."""
    _validar("liberação manual", x_api_key)


def chaves_ainda_no_padrao_dev() -> list[str]:
    """Usado só para avisar no startup quais chaves ainda não foram trocadas."""
    return [
        totem for totem, (nome_env, padrao_dev) in _CHAVES_PADRAO_DEV.items()
        if os.environ.get(nome_env, padrao_dev) == padrao_dev
    ]
