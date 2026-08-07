"""
Cobre o papel "operador" (estacionamento assistido -- alguém loga e faz na
mão o que o totem faria sozinho), a mensalidade configurável por unidade,
a revalidação de cupom no totem de saída e a criação/gestão de usuários
avulsos pelo painel.
"""
from datetime import timedelta

from app.auth import gerar_hash_senha
from app import models
from app.tempo import agora_utc
from tests.conftest import CNPJ_ESTABELECIMENTO_TESTE, fabricar_chave_nfce


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
# OPERADOR -- faz operação do dia a dia, não acessa configuração
# ---------------------------------------------------------------------
def test_operador_emite_ticket_e_verifica_saida(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token = _login(client_com_autenticacao_real, "operador1")

    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    assert ticket.status_code == 200

    resp = client_com_autenticacao_real.get(
        f"/saida/verificar/{ticket.json()['codigo_barras']}", headers=_auth(token)
    )
    assert resp.status_code == 200


def test_operador_nao_acessa_configuracao(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token = _login(client_com_autenticacao_real, "operador1")

    assert client_com_autenticacao_real.get("/gestao/credenciados", headers=_auth(token)).status_code == 403
    assert client_com_autenticacao_real.get("/gestao/estabelecimentos", headers=_auth(token)).status_code == 403
    assert client_com_autenticacao_real.get("/gestao/unidades", headers=_auth(token)).status_code == 403
    assert client_com_autenticacao_real.get("/gestao/usuarios", headers=_auth(token)).status_code == 403


def test_operador_consulta_tickets_mas_nao_gestao(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token = _login(client_com_autenticacao_real, "operador1")

    client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    resp = client_com_autenticacao_real.get("/gestao/relatorio/tickets", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_operador_com_permissao_faz_liberacao_manual(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1, pode_liberar_manualmente=True)
    token = _login(client_com_autenticacao_real, "operador1")

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual", headers=_auth(token), json={"cancela": "entrada", "motivo": "teste"}
    )
    assert resp.status_code == 200
    assert resp.json()["usuario_nome"] == "operador1"


def test_operador_sem_permissao_nao_faz_liberacao_manual(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1, pode_liberar_manualmente=False)
    token = _login(client_com_autenticacao_real, "operador1")

    resp = client_com_autenticacao_real.post(
        "/gestao/liberacao-manual", headers=_auth(token), json={"cancela": "entrada", "motivo": "teste"}
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------
# REVALIDAÇÃO DE CUPOM NO TOTEM DE SAÍDA
# ---------------------------------------------------------------------
def test_totem_de_saida_pode_validar_cupom(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "saida1", models.PapelUsuario.totem_saida, unidade_id=1)

    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada)).json()

    token_saida = _login(client_com_autenticacao_real, "saida1")
    resp = client_com_autenticacao_real.post(
        "/loja/validar-cupom", headers=_auth(token_saida),
        json={
            "codigo_barras": ticket["codigo_barras"],
            "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_ESTABELECIMENTO_TESTE, sufixo=7),
            "valor_compra": 20.0,
        },
    )
    assert resp.status_code == 200


def test_totem_de_saida_revalida_cupom_apos_ticket_ficar_tarifado(client_com_autenticacao_real, db_session):
    """Se o cliente chega na cancela sem cupom, /saida/verificar tarifa o
    ticket -- o totem de saída ainda precisa poder validar o cupom ali
    (revalidação) e recalcular a tolerância chamando /saida/verificar de
    novo, sem precisar de intervenção manual."""
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "saida1", models.PapelUsuario.totem_saida, unidade_id=1)

    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada)).json()

    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=30)
    db_session.commit()

    token_saida = _login(client_com_autenticacao_real, "saida1")
    primeira_verificacao = client_com_autenticacao_real.get(
        f"/saida/verificar/{ticket['codigo_barras']}", headers=_auth(token_saida)
    )
    assert primeira_verificacao.status_code == 200
    assert primeira_verificacao.json()["liberar_cancela"] is False  # tarifado, sem cupom

    resp = client_com_autenticacao_real.post(
        "/loja/validar-cupom", headers=_auth(token_saida),
        json={
            "codigo_barras": ticket["codigo_barras"],
            "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_ESTABELECIMENTO_TESTE, sufixo=8),
            "valor_compra": 20.0,
        },
    )
    assert resp.status_code == 200  # não bloqueia mais por o ticket estar "tarifado"

    segunda_verificacao = client_com_autenticacao_real.get(
        f"/saida/verificar/{ticket['codigo_barras']}", headers=_auth(token_saida)
    )
    assert segunda_verificacao.status_code == 200
    assert segunda_verificacao.json()["liberar_cancela"] is True  # tolerância maior agora libera


def test_validar_cupom_e_rejeitado_para_ticket_ja_finalizado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "saida1", models.PapelUsuario.totem_saida, unidade_id=1)

    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada)).json()

    token_saida = _login(client_com_autenticacao_real, "saida1")
    client_com_autenticacao_real.get(f"/saida/verificar/{ticket['codigo_barras']}", headers=_auth(token_saida))  # isento, finaliza

    resp = client_com_autenticacao_real.post(
        "/loja/validar-cupom", headers=_auth(token_saida),
        json={
            "codigo_barras": ticket["codigo_barras"],
            "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_ESTABELECIMENTO_TESTE, sufixo=9),
            "valor_compra": 20.0,
        },
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------
# MENSALIDADE CONFIGURÁVEL POR UNIDADE
# ---------------------------------------------------------------------
def test_renovar_mensalidade_usa_valor_e_dias_configurados_na_unidade(client, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=1).first()
    unidade.valor_mensalidade = 350.0
    unidade.dias_validade_mensalidade = 45
    db_session.commit()

    mensalista = client.post("/gestao/credenciados", json={
        "nome": "Fulano", "tipo": "mensalista", "identificador_facial": "FACE-MENSAL",
    }).json()

    resp = client.post(f"/gestao/credenciados/{mensalista['id']}/renovar", json={"forma_pagamento": "pix"})
    assert resp.status_code == 200

    pagamento = db_session.query(models.PagamentoMensalidade).filter_by(credenciado_id=mensalista["id"]).first()
    assert pagamento.valor == 350.0
    assert pagamento.dias_adicionados == 45


def test_renovar_mensalidade_aceita_valor_pontual_customizado(client, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=1).first()
    unidade.valor_mensalidade = 350.0
    db_session.commit()

    mensalista = client.post("/gestao/credenciados", json={
        "nome": "Fulano", "tipo": "mensalista", "identificador_facial": "FACE-PROMO",
    }).json()

    resp = client.post(f"/gestao/credenciados/{mensalista['id']}/renovar", json={"valor": 150.0, "forma_pagamento": "pix"})
    assert resp.status_code == 200

    pagamento = db_session.query(models.PagamentoMensalidade).filter_by(credenciado_id=mensalista["id"]).first()
    assert pagamento.valor == 150.0  # ajuste pontual não usa o valor da unidade


def test_criar_unidade_com_mensalidade_customizada(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/unidades", headers=_auth(token),
        json={"nome": "Unidade Premium", "valor_mensalidade": 500.0, "dias_validade_mensalidade": 60},
    )
    assert resp.status_code == 200
    unidade = resp.json()["unidade"]
    assert unidade["valor_mensalidade"] == 500.0
    assert unidade["dias_validade_mensalidade"] == 60


# ---------------------------------------------------------------------
# CRUD DE USUÁRIOS AVULSOS
# ---------------------------------------------------------------------
def test_dono_cria_operador_com_cpf_como_username(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "João Operador", "papel": "operador", "cpf": "12345678901", "unidade_id": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["usuario"]["username"] == "12345678901"
    assert data["usuario"]["papel"] == "operador"
    assert data["usuario"]["unidade_id"] == 1
    assert len(data["senha"]) > 6

    login = client_com_autenticacao_real.post(
        "/auth/login", json={"username": "12345678901", "senha": data["senha"]}
    )
    assert login.status_code == 200


def test_dono_cria_usuario_com_senha_customizada(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={
            "nome": "João Operador", "papel": "operador", "cpf": "12345678901",
            "unidade_id": 1, "senha": "minha-senha-escolhida",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["senha"] == "minha-senha-escolhida"

    login = client_com_autenticacao_real.post(
        "/auth/login", json={"username": "12345678901", "senha": "minha-senha-escolhida"}
    )
    assert login.status_code == 200


def test_criar_usuario_com_senha_curta_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={
            "nome": "João Operador", "papel": "operador", "cpf": "12345678901",
            "unidade_id": 1, "senha": "123",
        },
    )
    assert resp.status_code == 422


def test_criar_operador_com_cpf_invalido_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "João Operador", "papel": "operador", "cpf": "123", "unidade_id": 1},
    )
    assert resp.status_code == 422


def test_gerente_so_cria_operador_para_propria_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.gerente, unidade_id=1)
    token = _login(client_com_autenticacao_real, "gerente1")

    negado = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "Outro Gerente", "papel": "gerente", "unidade_id": 1},
    )
    assert negado.status_code == 403

    permitido = client_com_autenticacao_real.post(
        "/gestao/usuarios", headers=_auth(token),
        json={"nome": "Maria Operadora", "papel": "operador", "cpf": "98765432100"},
    )
    assert permitido.status_code == 200
    assert permitido.json()["usuario"]["unidade_id"] == 1


def test_listar_usuarios_escopado_por_unidade(client_com_autenticacao_real, db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()

    _criar_usuario(db_session, "gerente-a", models.PapelUsuario.gerente, unidade_id=1)
    _criar_usuario(db_session, "operador-a", models.PapelUsuario.operador, unidade_id=1)
    _criar_usuario(db_session, "operador-b", models.PapelUsuario.operador, unidade_id=unidade_b.id)

    token_a = _login(client_com_autenticacao_real, "gerente-a")
    lista_a = client_com_autenticacao_real.get("/gestao/usuarios", headers=_auth(token_a))
    assert lista_a.status_code == 200
    usernames = {u["username"] for u in lista_a.json()}
    assert usernames == {"gerente-a", "operador-a"}


def test_gerente_nao_ativa_usuario_de_outra_unidade(client_com_autenticacao_real, db_session):
    unidade_b = models.Unidade(nome="Unidade B", tolerancia_padrao_minutos=15)
    db_session.add(unidade_b)
    db_session.commit()

    _criar_usuario(db_session, "gerente-a", models.PapelUsuario.gerente, unidade_id=1)
    operador_b = _criar_usuario(db_session, "operador-b", models.PapelUsuario.operador, unidade_id=unidade_b.id)

    token_a = _login(client_com_autenticacao_real, "gerente-a")
    resp = client_com_autenticacao_real.patch(
        f"/gestao/usuarios/{operador_b.id}", headers=_auth(token_a), json={"ativo": False}
    )
    assert resp.status_code == 404


def test_desativar_usuario_impede_login(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    operador = _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token_dono = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.patch(
        f"/gestao/usuarios/{operador.id}", headers=_auth(token_dono), json={"ativo": False}
    )
    assert resp.status_code == 200
    assert resp.json()["ativo"] is False

    login = client_com_autenticacao_real.post(
        "/auth/login", json={"username": "operador1", "senha": "senha123"}
    )
    assert login.status_code == 401
