"""
Cobre o fluxo de acesso por reconhecimento facial: credenciados (sempre
liberados) e mensalistas (liberados enquanto a mensalidade estiver em dia).
"""
from datetime import timedelta

from app import models
from app.tempo import agora_utc


def _cadastrar_credenciado(client, **overrides):
    payload = {
        "nome": "Fulano de Tal",
        "tipo": "credenciado",
        "identificador_facial": "FACE-001",
        "documento": "111.111.111-11",
        "placa": "ABC1D23",
        "empresa_vinculo": "Loja Parceira",
    }
    payload.update(overrides)
    resp = client.post("/gestao/credenciados", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_credenciado_sempre_libera_entrada_e_saida(client):
    _cadastrar_credenciado(client)

    entrada = client.post("/credenciados/entrada", json={"identificador_facial": "FACE-001"})
    assert entrada.status_code == 200
    assert entrada.json()["liberar_cancela"] is True

    saida = client.post("/credenciados/saida", json={"identificador_facial": "FACE-001"})
    assert saida.status_code == 200
    assert saida.json()["liberar_cancela"] is True


def test_credenciado_nao_pode_entrar_duas_vezes_sem_sair(client):
    _cadastrar_credenciado(client)
    client.post("/credenciados/entrada", json={"identificador_facial": "FACE-001"})

    segunda_entrada = client.post("/credenciados/entrada", json={"identificador_facial": "FACE-001"})
    assert segunda_entrada.status_code == 409


def test_identificador_facial_desconhecido_e_rejeitado(client):
    resp = client.post("/credenciados/entrada", json={"identificador_facial": "NAO-CADASTRADO"})
    assert resp.status_code == 404


def test_credenciado_inativo_e_rejeitado(client, db_session):
    cadastrado = _cadastrar_credenciado(client)
    credenciado = db_session.get(models.Credenciado, cadastrado["id"])
    credenciado.ativo = False
    db_session.commit()

    resp = client.post("/credenciados/entrada", json={"identificador_facial": "FACE-001"})
    assert resp.status_code == 404


def test_mensalista_sem_pagamento_e_bloqueado(client):
    _cadastrar_credenciado(client, tipo="mensalista", identificador_facial="FACE-MENSAL-1")

    resp = client.post("/credenciados/entrada", json={"identificador_facial": "FACE-MENSAL-1"})
    assert resp.status_code == 200
    assert resp.json()["liberar_cancela"] is False


def test_mensalista_libera_apos_pagar(client):
    cadastrado = _cadastrar_credenciado(client, tipo="mensalista", identificador_facial="FACE-MENSAL-2")

    renovacao = client.post(f"/gestao/credenciados/{cadastrado['id']}/renovar", json={"valor": 200.0})
    assert renovacao.status_code == 200
    assert renovacao.json()["data_validade"] is not None

    resp = client.post("/credenciados/entrada", json={"identificador_facial": "FACE-MENSAL-2"})
    assert resp.status_code == 200
    assert resp.json()["liberar_cancela"] is True


def test_mensalista_vencido_volta_a_ser_bloqueado(client, db_session):
    cadastrado = _cadastrar_credenciado(client, tipo="mensalista", identificador_facial="FACE-MENSAL-3")
    client.post(f"/gestao/credenciados/{cadastrado['id']}/renovar", json={"valor": 200.0})

    credenciado = db_session.get(models.Credenciado, cadastrado["id"])
    credenciado.data_validade = agora_utc() - timedelta(days=1)
    db_session.commit()

    resp = client.post("/credenciados/entrada", json={"identificador_facial": "FACE-MENSAL-3"})
    assert resp.status_code == 200
    assert resp.json()["liberar_cancela"] is False


def test_renovacao_antecipada_nao_perde_dias_restantes(client, db_session):
    cadastrado = _cadastrar_credenciado(client, tipo="mensalista", identificador_facial="FACE-MENSAL-4")
    client.post(f"/gestao/credenciados/{cadastrado['id']}/renovar", json={"valor": 200.0})

    credenciado = db_session.get(models.Credenciado, cadastrado["id"])
    validade_antes = credenciado.data_validade
    assert validade_antes is not None

    # renova de novo, ainda dentro do prazo
    client.post(f"/gestao/credenciados/{cadastrado['id']}/renovar", json={"valor": 200.0})

    db_session.refresh(credenciado)
    # a nova validade deve ser a antiga + 30 dias (não "hoje + 30")
    assert credenciado.data_validade == validade_antes + timedelta(days=30)


def test_renovacao_so_se_aplica_a_mensalista(client):
    cadastrado = _cadastrar_credenciado(client, tipo="credenciado")
    resp = client.post(f"/gestao/credenciados/{cadastrado['id']}/renovar", json={"valor": 200.0})
    assert resp.status_code == 409


def test_cadastro_duplicado_de_identificador_facial_e_rejeitado(client):
    _cadastrar_credenciado(client)
    resp = client.post("/gestao/credenciados", json={
        "nome": "Outra Pessoa",
        "tipo": "credenciado",
        "identificador_facial": "FACE-001",
    })
    assert resp.status_code == 409


def test_desativar_credenciado_via_atualizacao(client):
    cadastrado = _cadastrar_credenciado(client)
    resp = client.patch(f"/gestao/credenciados/{cadastrado['id']}", json={"ativo": False})
    assert resp.status_code == 200
    assert resp.json()["ativo"] is False
