"""
Integração com a Pagar.me para cobrança PIX no totem de saída -- ver
https://docs.pagar.me/reference (API v5, /core/v5/orders).

Chave de API em PAGARME_API_KEY (variável de ambiente/.env). Sem ela
configurada, criar_cobranca_pix() levanta PagarMeNaoConfigurado com uma
mensagem clara em vez de fingir que funcionou -- o totem mostra essa
mensagem e cai pro operador tentar outra forma de pagamento.

ATENÇÃO: os nomes de campo usados abaixo (items/payments/pix/
charges[0].last_transaction.qr_code, status "paid") seguem a
documentação pública da Pagar.me v5, mas nunca foram testados contra
uma conta de verdade -- não havia credenciais disponíveis para testar
ao escrever isso. Antes de ativar em produção: gerar uma chave de teste
no dashboard da Pagar.me, rodar criar_cobranca_pix() contra o sandbox e
conferir se os campos da resposta batem exatamente (senão ajustar aqui,
é o único lugar que precisa mudar -- main.py só chama essas duas
funções, sem conhecer o formato da Pagar.me).

Pagar.me também costuma exigir um `customer` (nome + documento) pra
cobranças PIX, por exigência regulatória -- o totem hoje não coleta CPF
do motorista em nenhum momento. Se a API rejeitar a cobrança por falta
de customer, é preciso decidir entre pedir o CPF na tela de pagamento
ou usar um customer genérico (se a Pagar.me aceitar) -- não dava pra
resolver isso sem testar contra a API de verdade.
"""
import os
from datetime import timedelta

import requests

from .tempo import agora_utc

PAGARME_API_KEY = os.getenv("PAGARME_API_KEY", "")
PAGARME_BASE_URL = "https://api.pagar.me/core/v5"


class PagarMeNaoConfigurado(Exception):
    pass


def criar_cobranca_pix(valor: float, referencia: str, expira_em_segundos: int = 1800) -> dict:
    """Cria uma cobrança PIX. Retorna {"order_id", "qr_code_texto",
    "status", "expira_em"}. Levanta PagarMeNaoConfigurado se a chave de
    API não estiver definida, ou requests.HTTPError se a Pagar.me
    recusar a requisição (ex: payload inválido, credencial errada)."""
    if not PAGARME_API_KEY:
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
            }],
            "payments": [{
                "payment_method": "pix",
                "pix": {"expires_in": expira_em_segundos},
            }],
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
    if not PAGARME_API_KEY:
        raise PagarMeNaoConfigurado("Pagamento PIX ainda não configurado nesta unidade.")
    resp = requests.get(f"{PAGARME_BASE_URL}/orders/{order_id}", auth=(PAGARME_API_KEY, ""), timeout=15)
    resp.raise_for_status()
    return resp.json().get("status", "pending")
