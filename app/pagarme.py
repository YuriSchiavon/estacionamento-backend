"""
Integração com a Pagar.me para cobrança PIX no totem de saída -- chama
a API REST diretamente (POST /orders), ver
https://github.com/pagarme/pagarme-python-sdk/tree/main/doc/models
para o formato exato dos campos (a biblioteca oficial em Python,
pagarmeapisdk, não está publicada no PyPI -- só no GitHub deles --
então preferimos não depender de instalar direto de lá num build de
produção que não dá pra testar localmente; os nomes de campo abaixo
foram conferidos um a um contra a documentação oficial dos modelos).

Chave de API em PAGARME_API_KEY (variável de ambiente/.env). Sem ela
configurada, criar_cobranca_pix() levanta PagarMeNaoConfigurado com uma
mensagem clara -- o totem mostra essa mensagem e cai pro operador
tentar outra forma de pagamento.

Cliente genérico do estabelecimento: a Pagar.me exige um "customer"
(nome/documento/endereço/telefone) pra criar qualquer cobrança -- não
dá pra criar um PIX anônimo. O totem não coleta CPF do motorista em
nenhuma etapa (decisão consciente, pra não adicionar fricção no
autoatendimento), então todas as cobranças PIX usam um único cliente
fixo, o do próprio estabelecimento -- as cobranças continuam
identificáveis pelo código do ticket (ver `referencia` em
criar_cobranca_pix), só não pelo CPF de quem pagou. Preencher os dados
reais da empresa em PAGARME_CLIENTE_* antes de ativar em produção.
"""
import os
from datetime import timedelta

import requests

from .tempo import agora_utc

PAGARME_API_KEY = os.getenv("PAGARME_API_KEY", "")
PAGARME_BASE_URL = "https://api.pagar.me/core/v5"

PAGARME_CLIENTE_NOME = os.getenv("PAGARME_CLIENTE_NOME", "")
PAGARME_CLIENTE_DOCUMENTO = os.getenv("PAGARME_CLIENTE_DOCUMENTO", "")  # CPF ou CNPJ, só dígitos
PAGARME_CLIENTE_TIPO_DOCUMENTO = os.getenv("PAGARME_CLIENTE_TIPO_DOCUMENTO", "company")  # "individual" ou "company"
PAGARME_CLIENTE_EMAIL = os.getenv("PAGARME_CLIENTE_EMAIL", "")
PAGARME_CLIENTE_ENDERECO_RUA = os.getenv("PAGARME_CLIENTE_ENDERECO_RUA", "")
PAGARME_CLIENTE_ENDERECO_NUMERO = os.getenv("PAGARME_CLIENTE_ENDERECO_NUMERO", "")
PAGARME_CLIENTE_ENDERECO_BAIRRO = os.getenv("PAGARME_CLIENTE_ENDERECO_BAIRRO", "")
PAGARME_CLIENTE_ENDERECO_CIDADE = os.getenv("PAGARME_CLIENTE_ENDERECO_CIDADE", "")
PAGARME_CLIENTE_ENDERECO_ESTADO = os.getenv("PAGARME_CLIENTE_ENDERECO_ESTADO", "")  # sigla, ex "SP"
PAGARME_CLIENTE_ENDERECO_CEP = os.getenv("PAGARME_CLIENTE_ENDERECO_CEP", "")


class PagarMeNaoConfigurado(Exception):
    pass


def _configurado() -> bool:
    campos = [
        PAGARME_API_KEY, PAGARME_CLIENTE_NOME, PAGARME_CLIENTE_DOCUMENTO, PAGARME_CLIENTE_EMAIL,
        PAGARME_CLIENTE_ENDERECO_RUA, PAGARME_CLIENTE_ENDERECO_NUMERO, PAGARME_CLIENTE_ENDERECO_BAIRRO,
        PAGARME_CLIENTE_ENDERECO_CIDADE, PAGARME_CLIENTE_ENDERECO_ESTADO, PAGARME_CLIENTE_ENDERECO_CEP,
    ]
    return all(campos)


def _customer_generico() -> dict:
    endereco = {
        "street": PAGARME_CLIENTE_ENDERECO_RUA,
        "number": PAGARME_CLIENTE_ENDERECO_NUMERO,
        "neighborhood": PAGARME_CLIENTE_ENDERECO_BAIRRO,
        "city": PAGARME_CLIENTE_ENDERECO_CIDADE,
        "state": PAGARME_CLIENTE_ENDERECO_ESTADO,
        "zip_code": PAGARME_CLIENTE_ENDERECO_CEP,
        "country": "BR",
        "line_1": f"{PAGARME_CLIENTE_ENDERECO_RUA}, {PAGARME_CLIENTE_ENDERECO_NUMERO}",
    }
    return {
        "name": PAGARME_CLIENTE_NOME,
        "email": PAGARME_CLIENTE_EMAIL,
        "document": PAGARME_CLIENTE_DOCUMENTO,
        "type": PAGARME_CLIENTE_TIPO_DOCUMENTO,
        "address": endereco,
        "code": "cliente-generico-totem",
    }


def criar_cobranca_pix(valor: float, referencia: str, expira_em_segundos: int = 1800) -> dict:
    """Cria uma cobrança PIX. Retorna {"order_id", "qr_code_texto",
    "status", "expira_em"}. Levanta PagarMeNaoConfigurado se a chave de
    API ou os dados do cliente genérico não estiverem definidos, ou
    requests.HTTPError se a Pagar.me recusar a requisição."""
    if not _configurado():
        raise PagarMeNaoConfigurado(
            "Pagamento PIX ainda não configurado nesta unidade -- fale com o administrador."
        )
    resp = requests.post(
        f"{PAGARME_BASE_URL}/orders",
        auth=(PAGARME_API_KEY, ""),
        json={
            "items": [{
                "amount": int(round(valor * 100)),  # centavos, inteiro
                "description": referencia,
                "quantity": 1,
                "category": "parking",
            }],
            "customer": _customer_generico(),
            "payments": [{
                "payment_method": "pix",
                "pix": {"expires_in": expira_em_segundos},
            }],
            "code": referencia,
            "closed": True,
        },
        timeout=15,
    )
    resp.raise_for_status()
    dados = resp.json()
    transacao = dados["charges"][0]["last_transaction"]
    return {
        "order_id": dados["id"],
        "qr_code_texto": transacao.get("qr_code"),
        "status": dados.get("status"),
        "expira_em": agora_utc() + timedelta(seconds=expira_em_segundos),
    }


def consultar_status(order_id: str) -> str:
    """Status cru retornado pela Pagar.me (ex: "pending", "paid",
    "canceled") -- main.py traduz pro StatusCobrancaPix daqui."""
    if not _configurado():
        raise PagarMeNaoConfigurado("Pagamento PIX ainda não configurado nesta unidade.")
    resp = requests.get(f"{PAGARME_BASE_URL}/orders/{order_id}", auth=(PAGARME_API_KEY, ""), timeout=15)
    resp.raise_for_status()
    return resp.json().get("status", "pending")
