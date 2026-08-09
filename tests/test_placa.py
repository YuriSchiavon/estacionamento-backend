"""
Cobre o campo opcional `placa` em POST /entrada -- só preenchido quando o
operador digita manualmente (ex: terminal POS sem leitor automático,
ver app/static/pos.html). Totens continuam sem informar nada.
"""
from app import models
from tests.conftest import UNIDADE_TESTE_ID


def test_entrada_com_placa_salva_e_devolve_em_maiusculas(client, db_session):
    resp = client.post("/entrada", params={"placa": "abc1d23"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["placa"] == "ABC1D23"

    ticket = db_session.query(models.Ticket).filter_by(codigo_barras=resp.json()["codigo_barras"]).first()
    assert ticket.placa == "ABC1D23"


def test_entrada_sem_placa_continua_funcionando(client, db_session):
    resp = client.post("/entrada")
    assert resp.status_code == 200, resp.text
    assert resp.json()["placa"] is None

    ticket = db_session.query(models.Ticket).filter_by(codigo_barras=resp.json()["codigo_barras"]).first()
    assert ticket.placa is None
    assert ticket.unidade_id == UNIDADE_TESTE_ID
