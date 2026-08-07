"""
Cobre o papel "gerente_operacoes" -- mesmas permissões do "dono" (multi-
unidade, acesso total), só o cargo/nome é diferente. Testa que ele
consegue fazer tudo que só dono conseguia antes (criar unidade, ver
"geral", exclusão definitiva) e que continua não precisando de
unidade_id pra si mesmo.
"""
from app.auth import gerar_hash_senha
from app import models


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


def test_gerente_operacoes_cria_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "geops1", models.PapelUsuario.gerente_operacoes)
    token = _login(client_com_autenticacao_real, "geops1")

    resp = client_com_autenticacao_real.post(
        "/gestao/unidades", headers=_auth(token), json={"nome": "Unidade Nova"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["contas"]) == 3


def test_gerente_operacoes_ve_geral_ou_filtra_por_unidade(client_com_autenticacao_real, db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()

    _criar_usuario(db_session, "geops1", models.PapelUsuario.gerente_operacoes)
    _criar_usuario(db_session, "entrada-a", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "entrada-b", models.PapelUsuario.totem_entrada, unidade_id=unidade_b.id)

    token_a = _login(client_com_autenticacao_real, "entrada-a")
    client_com_autenticacao_real.post("/entrada", headers=_auth(token_a))
    token_b = _login(client_com_autenticacao_real, "entrada-b")
    client_com_autenticacao_real.post("/entrada", headers=_auth(token_b))

    token_geops = _login(client_com_autenticacao_real, "geops1")
    geral = client_com_autenticacao_real.get("/gestao/relatorio/tickets", headers=_auth(token_geops))
    assert len(geral.json()) == 2

    so_a = client_com_autenticacao_real.get(
        "/gestao/relatorio/tickets?unidade_id=1", headers=_auth(token_geops)
    )
    assert len(so_a.json()) == 1


def test_gerente_operacoes_cria_outro_gerente_operacoes_sem_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "geops1", models.PapelUsuario.gerente_operacoes)
    token = _login(client_com_autenticacao_real, "geops1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "Outro Gerente de Operações", "papel": "gerente_operacoes"},
    )
    assert resp.status_code == 200
    assert resp.json()["usuario"]["unidade_id"] is None


def test_gerente_operacoes_faz_exclusao_definitiva_de_usuario(client_com_autenticacao_real, db_session):
    """Exclusão definitiva era exclusiva do dono -- gerente_operacoes tem o
    mesmo nível de acesso, então também consegue."""
    _criar_usuario(db_session, "geops1", models.PapelUsuario.gerente_operacoes)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token = _login(client_com_autenticacao_real, "geops1")

    resp = client_com_autenticacao_real.delete(f"/gestao/usuarios/{operador.id}", headers=_auth(token))
    assert resp.status_code == 200


def test_supervisor_nao_cria_unidade_nem_faz_exclusao_definitiva(client_com_autenticacao_real, db_session):
    """Supervisor (antigo "gerente") continua com o acesso restrito de
    sempre -- preso à própria unidade, sem exclusão definitiva."""
    _criar_usuario(db_session, "supervisor1", models.PapelUsuario.supervisor, unidade_id=1)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token = _login(client_com_autenticacao_real, "supervisor1")

    negado_unidade = client_com_autenticacao_real.post(
        "/gestao/unidades", headers=_auth(token), json={"nome": "Unidade Nova"},
    )
    assert negado_unidade.status_code == 403

    negado_exclusao = client_com_autenticacao_real.delete(
        f"/gestao/usuarios/{operador.id}", headers=_auth(token)
    )
    assert negado_exclusao.status_code == 403
