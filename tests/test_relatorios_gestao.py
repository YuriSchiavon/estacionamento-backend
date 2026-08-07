"""
Cobre os relatórios do painel de gestão: tickets, conciliação financeira
e auditoria de tentativas de reuso de cupom fiscal. Dashboard e conciliação
detalhados ficam em test_dashboard_e_manutencao.py.
"""
from datetime import timedelta

from app.auth import gerar_hash_senha
from app import models
from app.tempo import agora_utc
from tests.conftest import CNPJ_ESTABELECIMENTO_TESTE, fabricar_chave_nfce


def _emitir_ticket(client):
    return client.post("/entrada").json()


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


def test_tentativa_de_cupom_duplicado_fica_registrada_na_auditoria(client):
    ticket_1 = _emitir_ticket(client)
    ticket_2 = _emitir_ticket(client)
    chave_auditada = fabricar_chave_nfce(CNPJ_ESTABELECIMENTO_TESTE, sufixo=3)

    client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket_1["codigo_barras"],
        "chave_acesso_nfce": chave_auditada,
        "valor_compra": 20.0,
    })
    resp_duplicada = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket_2["codigo_barras"],
        "chave_acesso_nfce": chave_auditada,
        "valor_compra": 20.0,
    })
    assert resp_duplicada.status_code == 409

    auditoria = client.get("/gestao/relatorio/cupons-duplicados")
    assert auditoria.status_code == 200
    registros = auditoria.json()
    assert len(registros) == 1
    assert registros[0]["chave_acesso_nfce"] == chave_auditada
    assert registros[0]["codigo_barras_tentativa"] == ticket_2["codigo_barras"]


def test_conciliacao_soma_transacoes_por_forma_de_pagamento(client, db_session):
    from datetime import timedelta
    from app import models
    from app.tempo import agora_utc

    ticket = _emitir_ticket(client)
    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=30)
    db_session.commit()

    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    valor = verificacao.json()["valor_calculado"]
    client.post("/saida/pagamento", json={
        "codigo_barras": ticket["codigo_barras"],
        "forma_pagamento": "pix",
        "valor": valor,
    })

    resp = client.get("/gestao/relatorio/conciliacao")
    assert resp.status_code == 200
    data = resp.json()
    assert data["valor_recebido"] == valor
    assert data["por_forma_pagamento"]["pix"] == valor
    assert data["tickets_tarifados_pagos"] == 1
    assert data["tickets_tarifados_sem_pagar"] == 0


def test_relatorio_tickets_lista_tickets_emitidos(client):
    _emitir_ticket(client)
    _emitir_ticket(client)

    resp = client.get("/gestao/relatorio/tickets")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_patio_estacionados_e_o_filtro_padrao(client, db_session):
    ainda_no_patio = _emitir_ticket(client)
    ja_saiu = _emitir_ticket(client)
    t = db_session.query(models.Ticket).filter_by(codigo_barras=ja_saiu["codigo_barras"]).first()
    t.status = models.StatusTicket.finalizado
    db_session.commit()

    resp = client.get("/gestao/relatorio/patio")
    assert resp.status_code == 200
    codigos = {item["codigo_barras"] for item in resp.json()}
    assert codigos == {ainda_no_patio["codigo_barras"]}


def test_patio_filtro_liberados(client, db_session):
    ticket = _emitir_ticket(client)
    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.status = models.StatusTicket.finalizado
    db_session.commit()

    resp = client.get("/gestao/relatorio/patio", params={"filtro": "liberados"})
    assert resp.status_code == 200
    codigos = {item["codigo_barras"] for item in resp.json()}
    assert codigos == {ticket["codigo_barras"]}


def test_patio_filtro_pagos(client, db_session):
    ticket = _emitir_ticket(client)
    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=30)
    db_session.commit()
    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}").json()
    client.post("/saida/pagamento", json={
        "codigo_barras": ticket["codigo_barras"], "forma_pagamento": "pix", "valor": verificacao["valor_calculado"],
    })

    outro_sem_pagar = _emitir_ticket(client)

    resp = client.get("/gestao/relatorio/patio", params={"filtro": "pagos"})
    assert resp.status_code == 200
    dados = resp.json()
    assert {item["codigo_barras"] for item in dados} == {ticket["codigo_barras"]}
    assert dados[0]["pago"] is True


def test_patio_filtro_credenciados(client):
    client.post("/gestao/credenciados", json={
        "nome": "Fulano", "tipo": "credenciado", "identificador_facial": "FACE-PATIO",
    })
    client.post("/credenciados/entrada", json={"identificador_facial": "FACE-PATIO"})
    _emitir_ticket(client)  # ticket normal, não deve aparecer

    resp = client.get("/gestao/relatorio/patio", params={"filtro": "credenciados"})
    assert resp.status_code == 200
    dados = resp.json()
    assert len(dados) == 1
    assert dados[0]["credenciado_nome"] == "Fulano"
    assert dados[0]["credenciado_tipo"] == "credenciado"


def test_operador_acessa_relatorio_de_patio(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "operador1", models.PapelUsuario.operador, unidade_id=1)
    token = _login(client_com_autenticacao_real, "operador1")

    client_com_autenticacao_real.post("/entrada", headers=_auth(token))
    resp = client_com_autenticacao_real.get("/gestao/relatorio/patio", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
