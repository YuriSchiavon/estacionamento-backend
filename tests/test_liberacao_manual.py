"""
Cobre a liberação manual de cancela pelo painel de gestão: motivo
obrigatório, vínculo opcional com um ticket (pode não existir, o ticket
pode ser o próprio motivo da falha) e registro de auditoria.
"""


def test_liberacao_manual_sem_ticket_funciona(client):
    resp = client.post("/gestao/liberacao-manual", json={
        "cancela": "entrada",
        "motivo": "Totem travou, sem ticket emitido",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["cancela"] == "entrada"
    assert data["ticket_id"] is None


def test_motivo_vazio_e_rejeitado(client):
    resp = client.post("/gestao/liberacao-manual", json={
        "cancela": "saida",
        "motivo": "   ",
    })
    assert resp.status_code == 422


def test_liberacao_manual_com_ticket_valido_finaliza_o_ticket(client):
    ticket = client.post("/entrada").json()

    resp = client.post("/gestao/liberacao-manual", json={
        "cancela": "saida",
        "motivo": "Cliente sem cartão, leitor de código com defeito",
        "ticket_id": ticket["id"],
    })
    assert resp.status_code == 200
    assert resp.json()["ticket_id"] == ticket["id"]

    relatorio = client.get("/gestao/relatorio/tickets").json()
    ticket_atualizado = next(t for t in relatorio if t["id"] == ticket["id"])
    assert ticket_atualizado["status"] == "finalizado"
    assert ticket_atualizado["data_hora_saida"] is not None


def test_liberacao_manual_com_ticket_inexistente_e_rejeitada(client):
    resp = client.post("/gestao/liberacao-manual", json={
        "cancela": "saida",
        "motivo": "teste",
        "ticket_id": 99999,
    })
    assert resp.status_code == 404


def test_liberacao_manual_fica_na_auditoria(client):
    client.post("/gestao/liberacao-manual", json={"cancela": "entrada", "motivo": "motivo 1"})
    client.post("/gestao/liberacao-manual", json={"cancela": "saida", "motivo": "motivo 2"})

    auditoria = client.get("/gestao/relatorio/liberacoes-manuais").json()
    assert len(auditoria) == 2
    motivos = {a["motivo"] for a in auditoria}
    assert motivos == {"motivo 1", "motivo 2"}
