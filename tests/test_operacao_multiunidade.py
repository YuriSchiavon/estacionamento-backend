"""
Cobre a operação multi-unidade: dono/gerente de operações/supervisor
passam a poder "ser o totem" pela tela de Operação (escolhendo a unidade),
e operador pode ganhar acesso a unidades extras além da própria (ver
app/security.py resolver_unidade_operacional/unidades_selecionaveis e
app/rotas_gestao.py unidades-autorizadas).
"""
from app.auth import gerar_hash_senha
from app import models
from tests.conftest import UNIDADE_TESTE_ID


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


def _criar_unidade_b(db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()
    return unidade_b


# ---------------------------------------------------------------------
# resolver_unidade_operacional -- via /entrada, exercitado pelos 3 perfis
# ---------------------------------------------------------------------
def test_dono_precisa_informar_unidade_para_registrar_entrada(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    sem_unidade = client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    assert sem_unidade.status_code == 422

    com_unidade = client_com_autenticacao_real.post(
        "/entrada", headers=_auth(token), params={"unidade_id": UNIDADE_TESTE_ID}
    )
    assert com_unidade.status_code == 200
    assert com_unidade.json()["unidade_id"] == UNIDADE_TESTE_ID


def test_supervisor_nao_escapa_da_propria_unidade_mesmo_informando_outra(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.post(
        "/entrada", headers=_auth(token), params={"unidade_id": unidade_b.id}
    )
    assert resp.status_code == 200
    assert resp.json()["unidade_id"] == UNIDADE_TESTE_ID  # ignora o que veio, usa a própria


def test_operador_sem_autorizacao_extra_e_ignorado_e_usa_propria_unidade(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "operador1")

    resp = client_com_autenticacao_real.post(
        "/entrada", headers=_auth(token), params={"unidade_id": unidade_b.id}
    )
    assert resp.status_code == 200
    assert resp.json()["unidade_id"] == UNIDADE_TESTE_ID


def test_operador_com_unidade_extra_autorizada_pode_operar_nela(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    db_session.add(models.UnidadeAutorizada(usuario_id=operador.id, unidade_id=unidade_b.id))
    db_session.commit()

    token = _login(client_com_autenticacao_real, "operador1")
    resp = client_com_autenticacao_real.post(
        "/entrada", headers=_auth(token), params={"unidade_id": unidade_b.id}
    )
    assert resp.status_code == 200
    assert resp.json()["unidade_id"] == unidade_b.id


# ---------------------------------------------------------------------
# Totens agora também aceitam dono/gerente_operacoes/supervisor (não só
# totem_* e operador) -- ver security._PAPEIS_OPERACAO_AMPLIADOS.
# ---------------------------------------------------------------------
def test_gerente_operacoes_pode_emitir_ticket_informando_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerop1", models.PapelUsuario.gerente_operacoes)
    token = _login(client_com_autenticacao_real, "gerop1")

    resp = client_com_autenticacao_real.post(
        "/entrada", headers=_auth(token), params={"unidade_id": UNIDADE_TESTE_ID}
    )
    assert resp.status_code == 200


def test_totem_de_entrada_de_verdade_continua_funcionando_sem_informar_unidade(client_com_autenticacao_real, db_session):
    """Regressão: totem de verdade nunca manda unidade_id -- continua preso
    à própria unidade, sem tela de seleção nenhuma."""
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "entrada1")

    resp = client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["unidade_id"] == UNIDADE_TESTE_ID


# ---------------------------------------------------------------------
# GET /auth/minhas-unidades
# ---------------------------------------------------------------------
def test_minhas_unidades_dono_ve_todas_as_ativas(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.get("/auth/minhas-unidades", headers=_auth(token))
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()}
    assert ids == {UNIDADE_TESTE_ID, unidade_b.id}


def test_minhas_unidades_supervisor_ve_so_a_propria(client_com_autenticacao_real, db_session):
    _criar_unidade_b(db_session)
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.get("/auth/minhas-unidades", headers=_auth(token))
    assert resp.status_code == 200
    assert [u["id"] for u in resp.json()] == [UNIDADE_TESTE_ID]


def test_minhas_unidades_operador_ve_propria_mais_autorizadas(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    db_session.add(models.UnidadeAutorizada(usuario_id=operador.id, unidade_id=unidade_b.id))
    db_session.commit()

    token = _login(client_com_autenticacao_real, "operador1")
    resp = client_com_autenticacao_real.get("/auth/minhas-unidades", headers=_auth(token))
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()}
    assert ids == {UNIDADE_TESTE_ID, unidade_b.id}


# ---------------------------------------------------------------------
# Criação de operador com unidades_autorizadas_ids + gestão pós-criação
# ---------------------------------------------------------------------
def test_criar_operador_com_unidades_autorizadas(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={
            "nome": "João Operador", "papel": "operador", "cpf": "12345678901",
            "unidade_id": UNIDADE_TESTE_ID, "unidades_autorizadas_ids": [unidade_b.id],
        },
    )
    assert resp.status_code == 200
    novo_id = resp.json()["usuario"]["id"]

    lista = client_com_autenticacao_real.get(
        f"/gestao/usuarios/{novo_id}/unidades-autorizadas", headers=_auth(token)
    )
    assert lista.status_code == 200
    assert [u["id"] for u in lista.json()] == [unidade_b.id]


def test_conceder_e_revogar_unidade_autorizada(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "dono1")

    conceder = client_com_autenticacao_real.post(
        f"/gestao/usuarios/{operador.id}/unidades-autorizadas", headers=_auth(token),
        json={"unidade_id": unidade_b.id},
    )
    assert conceder.status_code == 200
    assert [u["id"] for u in conceder.json()] == [unidade_b.id]

    revogar = client_com_autenticacao_real.delete(
        f"/gestao/usuarios/{operador.id}/unidades-autorizadas/{unidade_b.id}", headers=_auth(token),
    )
    assert revogar.status_code == 200
    assert revogar.json() == []


def test_supervisor_nao_pode_conceder_unidade_autorizada(client_com_autenticacao_real, db_session):
    """Conceder acesso a outra unidade é sempre coisa de dono/gerente de
    operações -- supervisor não tem autoridade sobre nenhuma unidade além
    da própria, então nem para um operador da própria unidade ele pode
    conceder (a unidade concedida nunca é a própria, por definição)."""
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID)
    operador_a = _criar_usuario(db_session, "operador-a", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "supervisor1")

    resp = client_com_autenticacao_real.post(
        f"/gestao/usuarios/{operador_a.id}/unidades-autorizadas", headers=_auth(token),
        json={"unidade_id": unidade_b.id},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------
# escopo_unidade -- relatórios de pátio/tickets também precisam respeitar
# a unidade extra autorizada, não só as ações de escrita (entrada, etc).
# ---------------------------------------------------------------------
def test_operador_consulta_patio_da_unidade_extra_autorizada(client_com_autenticacao_real, db_session):
    unidade_b = _criar_unidade_b(db_session)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    db_session.add(models.UnidadeAutorizada(usuario_id=operador.id, unidade_id=unidade_b.id))
    db_session.commit()
    token = _login(client_com_autenticacao_real, "operador1")

    client_com_autenticacao_real.post("/entrada", headers=_auth(token), params={"unidade_id": UNIDADE_TESTE_ID})
    client_com_autenticacao_real.post("/entrada", headers=_auth(token), params={"unidade_id": unidade_b.id})

    so_unidade_b = client_com_autenticacao_real.get(
        "/gestao/relatorio/patio", headers=_auth(token), params={"unidade_id": unidade_b.id}
    )
    assert so_unidade_b.status_code == 200
    assert len(so_unidade_b.json()) == 1
    assert so_unidade_b.json()[0]["unidade_id"] == unidade_b.id


def test_excluir_operador_remove_unidades_autorizadas(client_com_autenticacao_real, db_session):
    """Regressão: exclusão de usuário não pode falhar por causa das linhas
    em UnidadeAutorizada referenciando ele (FK)."""
    unidade_b = _criar_unidade_b(db_session)
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=UNIDADE_TESTE_ID)
    db_session.add(models.UnidadeAutorizada(usuario_id=operador.id, unidade_id=unidade_b.id))
    db_session.commit()

    token = _login(client_com_autenticacao_real, "dono1")
    resp = client_com_autenticacao_real.delete(f"/gestao/usuarios/{operador.id}", headers=_auth(token))
    assert resp.status_code == 200
