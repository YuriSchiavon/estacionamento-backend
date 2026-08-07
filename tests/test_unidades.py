"""
Cobre o cadastro de unidades e o isolamento entre elas: um totem ou
gerente de uma unidade nunca deve enxergar ou afetar dados de outra,
mesmo acertando um ID por adivinhação.
"""
from app.auth import gerar_hash_senha
from app import models


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


def test_dono_cria_unidade_com_contas_de_totem_funcionais(client_com_autenticacao_real, db_session):
    dono = _criar_usuario(db_session, "dono1", models.PapelUsuario.dono, pode_liberar_manualmente=True)
    token_dono = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/unidades", headers=_auth(token_dono),
        json={"nome": "Shopping Central", "tolerancia_padrao_minutos": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["contas"]) == 3
    papeis = {c["papel"] for c in data["contas"]}
    assert papeis == {"totem_entrada", "totem_validacao", "totem_saida"}

    conta_entrada = next(c for c in data["contas"] if c["papel"] == "totem_entrada")
    login_totem = client_com_autenticacao_real.post(
        "/auth/login", json={"username": conta_entrada["username"], "senha": conta_entrada["senha"]}
    )
    assert login_totem.status_code == 200
    assert login_totem.json()["unidade_id"] == data["unidade"]["id"]


def test_gerente_nao_pode_criar_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1)
    token = _login(client_com_autenticacao_real, "gerente1")

    resp = client_com_autenticacao_real.post(
        "/gestao/unidades", headers=_auth(token), json={"nome": "Outra Unidade"}
    )
    assert resp.status_code == 403


def test_totem_de_uma_unidade_nao_acessa_ticket_de_outra(client_com_autenticacao_real, db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()

    _criar_usuario(db_session, "entrada-a", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "saida-b", models.PapelUsuario.totem_saida, unidade_id=unidade_b.id)

    token_entrada_a = _login(client_com_autenticacao_real, "entrada-a")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada_a)).json()

    token_saida_b = _login(client_com_autenticacao_real, "saida-b")
    resp = client_com_autenticacao_real.get(
        f"/saida/verificar/{ticket['codigo_barras']}", headers=_auth(token_saida_b)
    )
    assert resp.status_code == 404  # não vaza que o ticket existe em outra unidade


def test_gerente_nao_acessa_credenciado_de_outra_unidade(client_com_autenticacao_real, db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()

    credenciado_b = models.Credenciado(
        unidade_id=unidade_b.id, nome="Fulano", tipo=models.TipoCredenciado.credenciado,
        identificador_facial="FACE-B",
    )
    db_session.add(credenciado_b)
    db_session.commit()

    _criar_usuario(db_session, "gerente-a", models.PapelUsuario.supervisor, unidade_id=1)
    token_a = _login(client_com_autenticacao_real, "gerente-a")

    resp = client_com_autenticacao_real.patch(
        f"/gestao/credenciados/{credenciado_b.id}", headers=_auth(token_a), json={"ativo": False}
    )
    assert resp.status_code == 404


def test_dono_ve_geral_ou_filtra_por_unidade(client_com_autenticacao_real, db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()

    _criar_usuario(db_session, "entrada-a", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "entrada-b", models.PapelUsuario.totem_entrada, unidade_id=unidade_b.id)
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)

    token_a = _login(client_com_autenticacao_real, "entrada-a")
    client_com_autenticacao_real.post("/entrada", headers=_auth(token_a))
    token_b = _login(client_com_autenticacao_real, "entrada-b")
    client_com_autenticacao_real.post("/entrada", headers=_auth(token_b))

    token_dono = _login(client_com_autenticacao_real, "dono1")

    geral = client_com_autenticacao_real.get("/gestao/relatorio/tickets", headers=_auth(token_dono))
    assert len(geral.json()) == 2

    so_a = client_com_autenticacao_real.get(
        "/gestao/relatorio/tickets?unidade_id=1", headers=_auth(token_dono)
    )
    assert len(so_a.json()) == 1
    assert so_a.json()[0]["unidade_id"] == 1


def test_limpar_patio_exige_unidade_explicita_para_dono(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono, pode_liberar_manualmente=True)
    token_dono = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual/limpar-patio", headers=_auth(token_dono),
        json={"cancela": "saida", "motivo": "teste"},
    )
    assert resp.status_code == 422
