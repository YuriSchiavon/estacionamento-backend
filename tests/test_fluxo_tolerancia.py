"""
Cobre os cenários de tolerância citados no README:
dentro do limite, no limite exato, excedido e cupom fiscal duplicado.
"""
from datetime import timedelta

from app import models
from app.tempo import agora_utc


def _emitir_ticket(client):
    resp = client.post("/entrada")
    assert resp.status_code == 200
    return resp.json()


def _envelhecer_ticket(db_session, codigo_barras: str, minutos: int):
    """Simula que o ticket entrou `minutos` atrás, sem depender do relógio real."""
    ticket = db_session.query(models.Ticket).filter_by(codigo_barras=codigo_barras).first()
    ticket.data_hora_entrada = agora_utc() - timedelta(minutes=minutos)
    db_session.commit()


def test_dentro_da_tolerancia_libera_sem_cobranca(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer_ticket(db_session, ticket["codigo_barras"], minutos=10)

    resp = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    data = resp.json()

    assert resp.status_code == 200
    assert data["liberar_cancela"] is True
    assert data["valor_calculado"] == 0.0


def test_no_limite_exato_ainda_libera(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer_ticket(db_session, ticket["codigo_barras"], minutos=15)  # tolerância padrão = 15

    resp = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    data = resp.json()

    assert resp.status_code == 200
    assert data["liberar_cancela"] is True
    assert data["valor_calculado"] == 0.0


def test_excedido_cobra_permanencia_inteira_e_nao_libera(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer_ticket(db_session, ticket["codigo_barras"], minutos=16)

    resp = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    data = resp.json()

    assert resp.status_code == 200
    assert data["liberar_cancela"] is False
    assert data["valor_calculado"] > 0.0


def test_tolerancia_maior_com_cupom_de_valor_alto(client, db_session):
    ticket = _emitir_ticket(client)
    client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket["codigo_barras"],
        "chave_acesso_nfce": "CHAVE-UNICA-001",
        "valor_compra": 50.0,  # >= 45 => 60 min de tolerância
    })
    _envelhecer_ticket(db_session, ticket["codigo_barras"], minutos=50)

    resp = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    data = resp.json()

    assert data["liberar_cancela"] is True
    assert data["tolerancia_aplicada_minutos"] == 60


def test_cupom_fiscal_duplicado_e_rejeitado(client):
    ticket_1 = _emitir_ticket(client)
    ticket_2 = _emitir_ticket(client)

    primeira = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket_1["codigo_barras"],
        "chave_acesso_nfce": "CHAVE-REPETIDA",
        "valor_compra": 20.0,
    })
    assert primeira.status_code == 200

    segunda = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket_2["codigo_barras"],
        "chave_acesso_nfce": "CHAVE-REPETIDA",
        "valor_compra": 20.0,
    })
    assert segunda.status_code == 409


def test_pagamento_libera_cancela_apos_exceder_tolerancia(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer_ticket(db_session, ticket["codigo_barras"], minutos=30)

    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    assert verificacao.json()["liberar_cancela"] is False
    valor = verificacao.json()["valor_calculado"]

    pagamento = client.post("/saida/pagamento", json={
        "codigo_barras": ticket["codigo_barras"],
        "forma_pagamento": "pix",
        "valor": valor,
    })
    assert pagamento.status_code == 200
    assert pagamento.json()["status"] == "pago"

    segunda_verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    data = segunda_verificacao.json()
    assert data["liberar_cancela"] is True
    assert data["motivo"] == "Pagamento já confirmado"


def test_ticket_inexistente_retorna_404(client):
    resp = client.get("/saida/verificar/CODIGO-QUE-NAO-EXISTE")
    assert resp.status_code == 404


def test_ticket_ja_finalizado_nao_pode_ser_verificado_de_novo(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer_ticket(db_session, ticket["codigo_barras"], minutos=5)

    primeira = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    assert primeira.json()["liberar_cancela"] is True

    segunda = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    assert segunda.status_code == 409
