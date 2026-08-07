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
    assert data["usuario_nome"] == "Usuário de Teste"


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
    assert all(a["usuario_nome"] == "Usuário de Teste" for a in auditoria)


def test_liberacao_manual_fica_na_auditoria_unificada(client):
    client.post("/gestao/liberacao-manual", json={"cancela": "entrada", "motivo": "motivo unificado"})

    auditoria = client.get("/gestao/relatorio/auditoria").json()
    assert len(auditoria) == 1
    evento = auditoria[0]
    assert evento["tipo"] == "liberacao_manual"
    assert "motivo unificado" in evento["descricao"]
    assert evento["usuario_nome"] == "Usuário de Teste"
    assert evento["detalhes"]["via_limpeza_patio"] is False


def test_auditoria_unificada_filtra_por_tipo(client):
    client.post("/gestao/liberacao-manual", json={"cancela": "entrada", "motivo": "motivo 1"})
    ticket = client.post("/entrada").json()
    client.post(f"/gestao/tickets/{ticket['id']}/excluir", json={"motivo": "engano"})

    apenas_exclusoes = client.get("/gestao/relatorio/auditoria", params={"tipo": "exclusao_ticket"}).json()
    assert len(apenas_exclusoes) == 1
    assert apenas_exclusoes[0]["tipo"] == "exclusao_ticket"

    tudo = client.get("/gestao/relatorio/auditoria").json()
    assert len(tudo) == 2
    # mais recente primeiro
    assert tudo[0]["data_hora"] >= tudo[1]["data_hora"]


def test_limpeza_de_patio_fica_na_auditoria_unificada_como_tipo_proprio(client):
    client.post("/entrada")
    client.post("/gestao/liberacao-manual/limpar-patio", json={"motivo": "falha geral"})

    auditoria = client.get("/gestao/relatorio/auditoria", params={"tipo": "liberacao_manual"}).json()
    assert len(auditoria) == 1
    assert auditoria[0]["detalhes"]["via_limpeza_patio"] is True
    assert "Limpeza de pátio" in auditoria[0]["descricao"]
