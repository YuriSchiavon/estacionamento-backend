"""
Cobre a conciliação financeira (diferença entre impresso/pago/liberado),
o dashboard operacional (movimento + pátio em tempo real) e as
ferramentas de manutenção do pátio: limpeza em massa e exclusão de ticket
avulso.
"""
from datetime import timedelta

from app import models
from app.tempo import agora_utc
from tests.conftest import CNPJ_ESTABELECIMENTO_TESTE, fabricar_chave_nfce


def _emitir_ticket(client):
    return client.post("/entrada").json()


def _envelhecer(db_session, codigo_barras, minutos):
    t = db_session.query(models.Ticket).filter_by(codigo_barras=codigo_barras).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=minutos)
    db_session.commit()


def test_conciliacao_nao_conta_isento_como_diferenca(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer(db_session, ticket["codigo_barras"], minutos=5)
    client.get(f"/saida/verificar/{ticket['codigo_barras']}")

    conciliacao = client.get("/gestao/relatorio/conciliacao").json()
    assert conciliacao["tickets_impressos"] == 1
    assert conciliacao["tickets_liberados"] == 1
    assert conciliacao["tickets_tarifados"] == 0  # isento não é tarifado

    dashboard = client.get("/gestao/dashboard").json()
    assert dashboard["entradas_no_periodo"] == 1
    assert dashboard["saidas_no_periodo"] == 1
    assert dashboard["veiculos_no_patio_agora"] == 0


def test_conciliacao_conta_ticket_tarifado_pago(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer(db_session, ticket["codigo_barras"], minutos=30)
    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}").json()
    client.post("/saida/pagamento", json={
        "codigo_barras": ticket["codigo_barras"],
        "forma_pagamento": "pix",
        "valor": verificacao["valor_calculado"],
    })
    client.get(f"/saida/verificar/{ticket['codigo_barras']}")  # finaliza após pagar

    data = client.get("/gestao/relatorio/conciliacao").json()
    assert data["tickets_tarifados"] == 1
    assert data["tickets_tarifados_pagos"] == 1
    assert data["tickets_tarifados_sem_pagar"] == 0
    assert data["valor_recebido"] == verificacao["valor_calculado"]
    assert data["diferenca_valor"] == 0.0


def test_conciliacao_e_dashboard_ticket_tarifado_pendente(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer(db_session, ticket["codigo_barras"], minutos=30)
    client.get(f"/saida/verificar/{ticket['codigo_barras']}")  # excede, não paga -- ainda no pátio

    conciliacao = client.get("/gestao/relatorio/conciliacao").json()
    assert conciliacao["tickets_tarifados"] == 1
    assert conciliacao["tickets_tarifados_pagos"] == 0
    assert conciliacao["tickets_tarifados_sem_pagar"] == 0  # ainda não saiu, não é "furo" ainda

    dashboard = client.get("/gestao/dashboard").json()
    assert dashboard["veiculos_no_patio_agora"] == 1
    assert dashboard["saidas_no_periodo"] == 0


def test_dashboard_conta_credenciado_e_mensalista_separadamente(client):
    client.post("/gestao/credenciados", json={
        "nome": "Fulano", "tipo": "credenciado", "identificador_facial": "FACE-A",
    })
    client.post("/credenciados/entrada", json={"identificador_facial": "FACE-A"})

    mensalista = client.post("/gestao/credenciados", json={
        "nome": "Beltrano", "tipo": "mensalista", "identificador_facial": "FACE-B",
    }).json()
    client.post(f"/gestao/credenciados/{mensalista['id']}/renovar", json={"valor": 200.0})
    client.post("/credenciados/entrada", json={"identificador_facial": "FACE-B"})

    dashboard = client.get("/gestao/dashboard").json()
    assert dashboard["acessos_credenciado_no_periodo"] == 1
    assert dashboard["acessos_mensalista_no_periodo"] == 1
    assert dashboard["veiculos_no_patio_credenciado"] == 1
    assert dashboard["veiculos_no_patio_mensalista"] == 1

    conciliacao = client.get("/gestao/relatorio/conciliacao").json()
    assert conciliacao["valor_mensalidades"] == 200.0


def test_conciliacao_conta_liberado_sem_pagar_como_diferenca(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer(db_session, ticket["codigo_barras"], minutos=30)
    client.get(f"/saida/verificar/{ticket['codigo_barras']}")  # tarifado, sem pagar

    client.post("/gestao/liberacao-manual", json={
        "cancela": "saida",
        "motivo": "Cliente sem cartão, liberado por decisão do gerente",
        "ticket_id": ticket["id"],
    })

    data = client.get("/gestao/relatorio/conciliacao").json()
    assert data["tickets_tarifados_sem_pagar"] == 1
    assert data["tickets_tarifados_pagos"] == 0
    assert data["diferenca_valor"] > 0


def test_limpar_patio_finaliza_tickets_abertos(client):
    ticket_1 = _emitir_ticket(client)
    ticket_2 = _emitir_ticket(client)

    # Sem campo "cancela" -- limpeza de pátio não abre nada fisicamente.
    resp = client.post("/gestao/liberacao-manual/limpar-patio", json={
        "motivo": "Falha geral no sistema às 18h",
    })
    assert resp.status_code == 200
    liberacoes = resp.json()
    assert len(liberacoes) == 2
    for liberacao in liberacoes:
        assert liberacao["cancela"] is None
        assert liberacao["via_limpeza_patio"] is True
        assert liberacao["usuario_nome"] == "Usuário de Teste"

    relatorio = client.get("/gestao/relatorio/tickets").json()
    codigos = {ticket_1["codigo_barras"], ticket_2["codigo_barras"]}
    for t in relatorio:
        if t["codigo_barras"] in codigos:
            assert t["status"] == "finalizado"


def test_limpar_patio_nao_mexe_em_ticket_de_credenciado(client):
    client.post("/gestao/credenciados", json={
        "nome": "Fulano", "tipo": "credenciado", "identificador_facial": "FACE-C",
    })
    client.post("/credenciados/entrada", json={"identificador_facial": "FACE-C"})

    resp = client.post("/gestao/liberacao-manual/limpar-patio", json={"motivo": "teste"})
    assert resp.status_code == 200
    assert resp.json() == []  # ticket de credenciado não é afetado


def test_excluir_ticket_avulso(client):
    ticket = _emitir_ticket(client)

    resp = client.post(f"/gestao/tickets/{ticket['id']}/excluir", json={
        "motivo": "Duplicado por engano no totem de entrada",
    })
    assert resp.status_code == 200
    assert resp.json()["codigo_barras"] == ticket["codigo_barras"]
    assert resp.json()["usuario_nome"] == "Usuário de Teste"

    relatorio = client.get("/gestao/relatorio/tickets").json()
    assert all(t["id"] != ticket["id"] for t in relatorio)

    auditoria = client.get("/gestao/relatorio/exclusoes-tickets").json()
    assert len(auditoria) == 1
    assert auditoria[0]["codigo_barras"] == ticket["codigo_barras"]
    assert auditoria[0]["usuario_nome"] == "Usuário de Teste"


def test_excluir_ticket_com_pagamento_e_rejeitado(client, db_session):
    ticket = _emitir_ticket(client)
    _envelhecer(db_session, ticket["codigo_barras"], minutos=30)
    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}").json()
    client.post("/saida/pagamento", json={
        "codigo_barras": ticket["codigo_barras"],
        "forma_pagamento": "pix",
        "valor": verificacao["valor_calculado"],
    })

    resp = client.post(f"/gestao/tickets/{ticket['id']}/excluir", json={"motivo": "teste"})
    assert resp.status_code == 409


def test_excluir_ticket_sem_motivo_e_rejeitado(client):
    ticket = _emitir_ticket(client)
    resp = client.post(f"/gestao/tickets/{ticket['id']}/excluir", json={"motivo": "   "})
    assert resp.status_code == 422
