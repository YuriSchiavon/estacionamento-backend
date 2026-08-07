"""
Cobre os relatórios do painel de gestão: tickets, conciliação financeira
e auditoria de tentativas de reuso de cupom fiscal. Dashboard e conciliação
detalhados ficam em test_dashboard_e_manutencao.py.
"""
from tests.conftest import CNPJ_ESTABELECIMENTO_TESTE, fabricar_chave_nfce


def _emitir_ticket(client):
    return client.post("/entrada").json()


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
