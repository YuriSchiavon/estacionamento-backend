"""
Cobre o papel totem_validacao (novo totem de auto-atendimento sem
controle de cancela, que processa validação de cupom E pagamento), o
QR code/nome da unidade no ticket impresso, e a permissão total de
dono/gerente de operações independente da flag pode_liberar_manualmente.
"""
from datetime import timedelta

from app.auth import gerar_hash_senha
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


# ---------------------------------------------------------------------
# totem_validacao processa pagamento (não só validação)
# ---------------------------------------------------------------------
def test_totem_validacao_consulta_saida_e_paga(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=UNIDADE_TESTE_ID)
    _criar_usuario(db_session, "validacao1", models.PapelUsuario.totem_validacao, unidade_id=UNIDADE_TESTE_ID)

    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada)).json()

    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=60)
    db_session.commit()

    token_validacao = _login(client_com_autenticacao_real, "validacao1")
    verificacao = client_com_autenticacao_real.get(
        f"/saida/verificar/{ticket['codigo_barras']}", headers=_auth(token_validacao)
    )
    assert verificacao.status_code == 200
    assert verificacao.json()["valor_calculado"] > 0

    pagamento = client_com_autenticacao_real.post(
        "/saida/pagamento", headers=_auth(token_validacao),
        json={"codigo_barras": ticket["codigo_barras"], "forma_pagamento": "pix", "valor": verificacao.json()["valor_calculado"]},
    )
    assert pagamento.status_code == 200
    assert pagamento.json()["status"] == "pago"


def test_totem_validacao_nao_abre_cancela_de_entrada(client_com_autenticacao_real, db_session):
    """totem_validacao processa pagamento, mas não tem nenhum caminho
    pra abrir a cancela de entrada -- isso continua exclusivo de
    totem_entrada (ou operação/gestão)."""
    _criar_usuario(db_session, "validacao1", models.PapelUsuario.totem_validacao, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "validacao1")

    resp = client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------
# QR code + nome da unidade no ticket impresso
# ---------------------------------------------------------------------
def test_entrada_devolve_qr_code_e_nome_da_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "entrada1")

    resp = client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["unidade_nome"] == "Unidade Teste"
    assert data["qr_code_svg"].startswith("<svg")


def test_pagamento_devolve_nome_da_unidade_mas_sem_qr(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=UNIDADE_TESTE_ID)
    _criar_usuario(db_session, "saida1", models.PapelUsuario.totem_saida, unidade_id=UNIDADE_TESTE_ID)
    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada)).json()

    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=60)
    db_session.commit()

    token_saida = _login(client_com_autenticacao_real, "saida1")
    verificacao = client_com_autenticacao_real.get(
        f"/saida/verificar/{ticket['codigo_barras']}", headers=_auth(token_saida)
    ).json()
    pagamento = client_com_autenticacao_real.post(
        "/saida/pagamento", headers=_auth(token_saida),
        json={"codigo_barras": ticket["codigo_barras"], "forma_pagamento": "pix", "valor": verificacao["valor_calculado"]},
    )
    assert pagamento.status_code == 200
    assert pagamento.json()["unidade_nome"] == "Unidade Teste"
    assert pagamento.json()["qr_code_svg"] is None


# ---------------------------------------------------------------------
# Dono/gerente de operações: liberação manual/limpeza de pátio sempre
# liberado, independente da flag pode_liberar_manualmente
# ---------------------------------------------------------------------
def test_dono_sem_flag_ainda_libera_manualmente(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono, pode_liberar_manualmente=False)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual", headers=_auth(token),
        json={"cancela": "entrada", "motivo": "teste", "unidade_id": UNIDADE_TESTE_ID},
    )
    assert resp.status_code == 200


def test_gerente_operacoes_sem_flag_ainda_limpa_patio(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerop1", models.PapelUsuario.gerente_operacoes, pode_liberar_manualmente=False)
    token = _login(client_com_autenticacao_real, "gerop1")

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual/limpar-patio", headers=_auth(token),
        json={"motivo": "teste", "unidade_id": UNIDADE_TESTE_ID},
    )
    assert resp.status_code == 200


def test_supervisor_sem_flag_continua_bloqueado(client_com_autenticacao_real, db_session):
    """Regressão: a flag continua valendo normalmente pra quem não é
    dono/gerente de operações -- só esses dois papéis ganharam o bypass."""
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID, pode_liberar_manualmente=False)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual", headers=_auth(token),
        json={"cancela": "entrada", "motivo": "teste"},
    )
    assert resp.status_code == 403
