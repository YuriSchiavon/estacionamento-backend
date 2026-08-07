"""
Cobre o fluxo de acesso por reconhecimento facial: credenciados (sempre
liberados) e mensalistas (liberados enquanto a mensalidade estiver em dia).
"""
from datetime import timedelta

from app.auth import gerar_hash_senha
from app import models
from app.tempo import agora_utc


def _criar_usuario(db_session, username, papel, unidade_id=None, senha="senha123"):
    usuario = models.Usuario(
        username=username, senha_hash=gerar_hash_senha(senha), nome=username,
        papel=papel, unidade_id=unidade_id,
    )
    db_session.add(usuario)
    db_session.commit()
    return usuario


def _login(client, username, senha="senha123"):
    resp = client.post("/auth/login", json={"username": username, "senha": senha})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


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


def test_excluir_credenciado_sem_historico_funciona(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    cadastrado = client_com_autenticacao_real.post(
        "/gestao/credenciados", headers=_auth(token),
        json={"nome": "Fulano", "tipo": "credenciado", "identificador_facial": "FACE-001", "unidade_id": 1},
    ).json()

    resp = client_com_autenticacao_real.delete(f"/gestao/credenciados/{cadastrado['id']}", headers=_auth(token))
    assert resp.status_code == 200

    lista = client_com_autenticacao_real.get("/gestao/credenciados", headers=_auth(token)).json()
    assert all(c["id"] != cadastrado["id"] for c in lista)


def test_excluir_credenciado_com_acesso_registrado_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    token = _login(client_com_autenticacao_real, "dono1")

    cadastrado = client_com_autenticacao_real.post(
        "/gestao/credenciados", headers=_auth(token),
        json={"nome": "Fulano", "tipo": "credenciado", "identificador_facial": "FACE-001", "unidade_id": 1},
    ).json()
    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    client_com_autenticacao_real.post(
        "/credenciados/entrada", headers=_auth(token_entrada), json={"identificador_facial": "FACE-001"}
    )

    resp = client_com_autenticacao_real.delete(f"/gestao/credenciados/{cadastrado['id']}", headers=_auth(token))
    assert resp.status_code == 409


def test_excluir_mensalista_com_pagamento_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    cadastrado = client_com_autenticacao_real.post(
        "/gestao/credenciados", headers=_auth(token),
        json={"nome": "Fulano", "tipo": "mensalista", "identificador_facial": "FACE-MENSAL-5", "unidade_id": 1},
    ).json()
    client_com_autenticacao_real.post(
        f"/gestao/credenciados/{cadastrado['id']}/renovar", headers=_auth(token), json={"valor": 200.0}
    )

    resp = client_com_autenticacao_real.delete(f"/gestao/credenciados/{cadastrado['id']}", headers=_auth(token))
    assert resp.status_code == 409


def test_gerente_nao_pode_excluir_credenciado(client_com_autenticacao_real, db_session):
    """Exclusão definitiva de credenciado é só do dono -- gerente só pode
    ativar/desativar (PATCH), não apagar de vez."""
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1)
    token = _login(client_com_autenticacao_real, "gerente1")

    criado = client_com_autenticacao_real.post(
        "/gestao/credenciados", headers=_auth(token),
        json={"nome": "Fulano", "tipo": "credenciado", "identificador_facial": "FACE-GERENTE"},
    ).json()

    resp = client_com_autenticacao_real.delete(f"/gestao/credenciados/{criado['id']}", headers=_auth(token))
    assert resp.status_code == 403
