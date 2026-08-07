"""
Testa o login de verdade (usuário/senha -> token) e o isolamento por
papel, sem o bypass usado nos testes de regra de negócio (ver conftest.py).
"""
from app.auth import gerar_hash_senha
from app import models

SENHA = "senha-de-teste-123"


def _criar_usuario(db_session, username, papel, unidade_id=None, pode_liberar_manualmente=False):
    usuario = models.Usuario(
        username=username, senha_hash=gerar_hash_senha(SENHA), nome=username,
        papel=papel, unidade_id=unidade_id, pode_liberar_manualmente=pode_liberar_manualmente,
    )
    db_session.add(usuario)
    db_session.commit()
    return usuario


def test_login_com_credenciais_corretas(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    resp = client_com_autenticacao_real.post("/auth/login", json={"username": "entrada1", "senha": SENHA})
    assert resp.status_code == 200
    data = resp.json()
    assert data["papel"] == "totem_entrada"
    assert data["unidade_id"] == 1
    assert len(data["token"]) > 20


def test_login_com_senha_errada_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    resp = client_com_autenticacao_real.post("/auth/login", json={"username": "entrada1", "senha": "errada"})
    assert resp.status_code == 401


def test_login_com_usuario_inexistente_e_rejeitado(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post("/auth/login", json={"username": "ninguem", "senha": SENHA})
    assert resp.status_code == 401


def test_sem_token_e_rejeitado(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post("/entrada")
    assert resp.status_code == 401


def test_token_invalido_e_rejeitado(client_com_autenticacao_real):
    resp = client_com_autenticacao_real.post("/entrada", headers={"Authorization": "Bearer token-que-nao-existe"})
    assert resp.status_code == 401


def test_papel_errado_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "saida1", models.PapelUsuario.totem_saida, unidade_id=1)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "saida1", "senha": SENHA})
    token = login.json()["token"]

    # conta de totem de saída tentando usar o endpoint de entrada
    resp = client_com_autenticacao_real.post("/entrada", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_totem_nao_acessa_painel_de_gestao(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "entrada1", "senha": SENHA})
    token = login.json()["token"]

    resp = client_com_autenticacao_real.get("/gestao/credenciados", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_gestao_sem_permissao_de_liberacao_manual_e_rejeitada(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1, pode_liberar_manualmente=False)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "gerente1", "senha": SENHA})
    token = login.json()["token"]

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual",
        headers={"Authorization": f"Bearer {token}"},
        json={"cancela": "saida", "motivo": "teste"},
    )
    assert resp.status_code == 403


def test_gestao_com_permissao_de_liberacao_manual_funciona(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente2", models.PapelUsuario.supervisor, unidade_id=1, pode_liberar_manualmente=True)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "gerente2", "senha": SENHA})
    token = login.json()["token"]

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual",
        headers={"Authorization": f"Bearer {token}"},
        json={"cancela": "saida", "motivo": "teste"},
    )
    assert resp.status_code == 200


def test_logout_revoga_o_token(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "entrada1", "senha": SENHA})
    token = login.json()["token"]

    logout = client_com_autenticacao_real.post("/auth/logout", json={"token": token})
    assert logout.status_code == 200

    resp = client_com_autenticacao_real.post("/entrada", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_trocar_senha_funciona_e_a_senha_nova_passa_a_valer(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "gerente1", "senha": SENHA})
    token = login.json()["token"]

    resp = client_com_autenticacao_real.post(
        "/auth/trocar-senha",
        headers={"Authorization": f"Bearer {token}"},
        json={"senha_atual": SENHA, "nova_senha": "nova-senha-456"},
    )
    assert resp.status_code == 200

    login_senha_antiga = client_com_autenticacao_real.post(
        "/auth/login", json={"username": "gerente1", "senha": SENHA}
    )
    assert login_senha_antiga.status_code == 401

    login_senha_nova = client_com_autenticacao_real.post(
        "/auth/login", json={"username": "gerente1", "senha": "nova-senha-456"}
    )
    assert login_senha_nova.status_code == 200


def test_trocar_senha_com_senha_atual_errada_e_rejeitada(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "gerente1", "senha": SENHA})
    token = login.json()["token"]

    resp = client_com_autenticacao_real.post(
        "/auth/trocar-senha",
        headers={"Authorization": f"Bearer {token}"},
        json={"senha_atual": "senha-errada", "nova_senha": "nova-senha-456"},
    )
    assert resp.status_code == 401


def test_trocar_senha_muito_curta_e_rejeitada(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1)
    login = client_com_autenticacao_real.post("/auth/login", json={"username": "gerente1", "senha": SENHA})
    token = login.json()["token"]

    resp = client_com_autenticacao_real.post(
        "/auth/trocar-senha",
        headers={"Authorization": f"Bearer {token}"},
        json={"senha_atual": SENHA, "nova_senha": "123"},
    )
    assert resp.status_code == 422
