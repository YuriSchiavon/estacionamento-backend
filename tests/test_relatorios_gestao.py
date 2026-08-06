"""
Cobre os relatórios do painel de gestão: tickets, financeiro e auditoria
de tentativas de reuso de cupom fiscal.
"""


def _emitir_ticket(client):
    return client.post("/entrada").json()


def test_tentativa_de_cupom_duplicado_fica_registrada_na_auditoria(client):
    ticket_1 = _emitir_ticket(client)
    ticket_2 = _emitir_ticket(client)

    client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket_1["codigo_barras"],
        "chave_acesso_nfce": "CHAVE-AUDITADA",
        "valor_compra": 20.0,
    })
    resp_duplicada = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket_2["codigo_barras"],
        "chave_acesso_nfce": "CHAVE-AUDITADA",
        "valor_compra": 20.0,
    })
    assert resp_duplicada.status_code == 409

    auditoria = client.get("/gestao/relatorio/cupons-duplicados")
    assert auditoria.status_code == 200
    registros = auditoria.json()
    assert len(registros) == 1
    assert registros[0]["chave_acesso_nfce"] == "CHAVE-AUDITADA"
    assert registros[0]["codigo_barras_tentativa"] == ticket_2["codigo_barras"]


def test_relatorio_financeiro_soma_transacoes_por_forma_de_pagamento(client, db_session):
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

    resp = client.get("/gestao/relatorio/financeiro")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_arrecadado"] == valor
    assert data["por_forma_pagamento"]["pix"] == valor
    assert data["quantidade_transacoes"] == 1


def test_relatorio_tickets_lista_tickets_emitidos(client):
    _emitir_ticket(client)
    _emitir_ticket(client)

    resp = client.get("/gestao/relatorio/tickets")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
