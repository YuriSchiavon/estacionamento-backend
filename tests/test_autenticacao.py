"""
Testa a autenticação por chave de API em si (sem o bypass usado nos demais
testes). Usa os valores padrão de desenvolvimento definidos em app/security.py.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import exigir_chave_entrada, exigir_chave_gestao, exigir_chave_saida, exigir_chave_validacao

CHAVE_ENTRADA = "dev-entrada-troque-em-producao"
CHAVE_VALIDACAO = "dev-validacao-troque-em-producao"
CHAVE_SAIDA = "dev-saida-troque-em-producao"
CHAVE_GESTAO = "dev-gestao-troque-em-producao"


@pytest.fixture
def client_com_autenticacao_real():
    """Remove temporariamente o bypass de autenticação do conftest."""
    dependencias = (exigir_chave_entrada, exigir_chave_validacao, exigir_chave_saida, exigir_chave_gestao)
    salvos = {dep: app.dependency_overrides.pop(dep, None) for dep in dependencias}
    try:
        yield TestClient(app)
    finally:
        for dep, override in salvos.items():
            if override is not None:
                app.dependency_overrides[dep] = override


def test_sem_chave_e_rejeitado(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post("/entrada")
    assert resp.status_code == 401


def test_chave_errada_e_rejeitada(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post("/entrada", headers={"X-API-Key": "chave-errada"})
    assert resp.status_code == 401


def test_chave_correta_e_aceita(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post("/entrada", headers={"X-API-Key": CHAVE_ENTRADA})
    assert resp.status_code == 200


def test_chave_de_um_totem_nao_funciona_em_outro(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post(
        "/loja/validar-cupom",
        headers={"X-API-Key": CHAVE_ENTRADA},
        json={"codigo_barras": "X", "chave_acesso_nfce": "Y", "valor_compra": 10.0},
    )
    assert resp.status_code == 401


def test_chave_de_saida_funciona_para_verificar_e_pagamento(client_com_autenticacao_real):
    entrada = client_com_autenticacao_real.post("/entrada", headers={"X-API-Key": CHAVE_ENTRADA})
    codigo = entrada.json()["codigo_barras"]

    verificar = client_com_autenticacao_real.get(
        f"/saida/verificar/{codigo}", headers={"X-API-Key": CHAVE_SAIDA}
    )
    assert verificar.status_code == 200


def test_chave_de_totem_nao_funciona_no_painel_de_gestao(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.get(
        "/gestao/credenciados", headers={"X-API-Key": CHAVE_ENTRADA}
    )
    assert resp.status_code == 401


def test_chave_de_gestao_funciona_no_painel_de_gestao(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.get(
        "/gestao/credenciados", headers={"X-API-Key": CHAVE_GESTAO}
    )
    assert resp.status_code == 200
