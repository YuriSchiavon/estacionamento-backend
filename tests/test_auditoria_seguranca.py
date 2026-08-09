"""
Cobre os achados da auditoria de segurança/negócio: pagamento não pode
aceitar valor menor que o devido, sessão de totem dura mais que a de
conta humana, e só quem já tem permissão de liberação manual pode
concedê-la pra outra conta.
"""
from datetime import timedelta

import pytest

from app.auth import DURACAO_SESSAO_HORAS, DURACAO_SESSAO_TOTEM_HORAS, gerar_hash_senha
from app import models
from app.tempo import agora_utc
from tests.conftest import UNIDADE_TESTE_ID


def _criar_usuario(db_session, username, papel, unidade_id=None, pode_liberar_manualmente=False, senha="senha123"):
    usuario = models.Usuario(
        username=username, senha_hash=gerar_hash_senha(senha), nome=username,
        papel=papel, unidade_id=unidade_id, pode_liberar_manualmente=pode_liberar_manualmente,
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


def _emitir_e_tarifar(client, db_session, unidade_id=UNIDADE_TESTE_ID):
    ticket = client.post("/entrada").json()
    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=60)
    db_session.commit()
    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}").json()
    return ticket["codigo_barras"], verificacao["valor_calculado"]


# ---------------------------------------------------------------------
# Pagamento não pode ser menor que o valor devido
# ---------------------------------------------------------------------
def test_pagamento_com_valor_menor_que_o_devido_e_rejeitado(client, db_session):
    codigo, valor_devido = _emitir_e_tarifar(client, db_session)
    assert valor_devido > 1.0  # garante que dá pra testar "menos que"

    resp = client.post("/saida/pagamento", json={
        "codigo_barras": codigo, "forma_pagamento": "pix", "valor": 0.01,
    })
    assert resp.status_code == 422

    # o ticket continua tarifado, não foi indevidamente liberado
    t = db_session.query(models.Ticket).filter_by(codigo_barras=codigo).first()
    assert t.status == models.StatusTicket.tarifado


def test_pagamento_com_valor_exato_e_aceito(client, db_session):
    codigo, valor_devido = _emitir_e_tarifar(client, db_session)
    resp = client.post("/saida/pagamento", json={
        "codigo_barras": codigo, "forma_pagamento": "pix", "valor": valor_devido,
    })
    assert resp.status_code == 200


def test_pagamento_com_valor_maior_e_aceito(client, db_session):
    """Sobrepagamento é permitido -- só subpagamento é bloqueado."""
    codigo, valor_devido = _emitir_e_tarifar(client, db_session)
    resp = client.post("/saida/pagamento", json={
        "codigo_barras": codigo, "forma_pagamento": "pix", "valor": valor_devido + 10,
    })
    assert resp.status_code == 200


def test_forma_pagamento_invalida_e_rejeitada(client, db_session):
    codigo, valor_devido = _emitir_e_tarifar(client, db_session)
    resp = client.post("/saida/pagamento", json={
        "codigo_barras": codigo, "forma_pagamento": "bitcoin", "valor": valor_devido,
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------
# Duração de sessão -- totem dura muito mais que conta humana
# ---------------------------------------------------------------------
def test_sessao_de_totem_dura_muito_mais_que_conta_humana(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=UNIDADE_TESTE_ID)
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)

    token_totem = _login(client_com_autenticacao_real, "entrada1")
    token_dono = _login(client_com_autenticacao_real, "dono1")

    sessao_totem = db_session.query(models.Sessao).filter_by(token=token_totem).first()
    sessao_dono = db_session.query(models.Sessao).filter_by(token=token_dono).first()

    duracao_totem_horas = (sessao_totem.expira_em - sessao_totem.criado_em).total_seconds() / 3600
    duracao_dono_horas = (sessao_dono.expira_em - sessao_dono.criado_em).total_seconds() / 3600

    # criado_em/expira_em vêm de duas chamadas a agora_utc() microssegundos
    # apart -- tolerância de 1s evita falso negativo por isso.
    assert duracao_totem_horas == pytest.approx(DURACAO_SESSAO_TOTEM_HORAS, abs=1 / 3600)
    assert duracao_dono_horas == pytest.approx(DURACAO_SESSAO_HORAS, abs=1 / 3600)
    assert duracao_totem_horas > duracao_dono_horas


# ---------------------------------------------------------------------
# Só quem já tem pode_liberar_manualmente pode concedê-la
# ---------------------------------------------------------------------
def test_supervisor_sem_flag_nao_pode_criar_operador_com_liberacao_manual(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID, pode_liberar_manualmente=False)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "Operador Novo", "papel": "operador", "cpf": "11122233344", "pode_liberar_manualmente": True},
    )
    assert resp.status_code == 403


def test_supervisor_com_flag_pode_criar_operador_com_liberacao_manual(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID, pode_liberar_manualmente=True)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "Operador Novo", "papel": "operador", "cpf": "11122233344", "pode_liberar_manualmente": True},
    )
    assert resp.status_code == 200


def test_supervisor_sem_flag_nao_pode_conceder_via_patch(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID, pode_liberar_manualmente=False)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID, pode_liberar_manualmente=False)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.patch(
        f"/gestao/usuarios/{operador.id}", headers=_auth(token), json={"pode_liberar_manualmente": True},
    )
    assert resp.status_code == 403

    db_session.refresh(operador)
    assert operador.pode_liberar_manualmente is False


def test_dono_pode_conceder_liberacao_manual_mesmo_sem_a_propria_flag(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono, pode_liberar_manualmente=False)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.patch(
        f"/gestao/usuarios/{operador.id}", headers=_auth(token), json={"pode_liberar_manualmente": True},
    )
    assert resp.status_code == 200
