"""
Cobre o ponto (entrada/saída/intervalo) e o caixa (abertura/fechamento de
turno de estacionamento assistido) -- ver Caixa/RegistroPonto em
app/models.py. Ponto e caixa são ações independentes no banco: bater
ponto de entrada é pré-requisito pra abrir caixa, mas fechar caixa não
bate ponto nenhum -- isso é sempre um passo separado, batido à parte
(ver terminal POS, que encadeia as telas nessa ordem).
"""
from app import models
from tests.conftest import UNIDADE_TESTE_ID


def _pagar(client, codigo, forma_pagamento, valor):
    resp = client.post("/saida/pagamento", json={
        "codigo_barras": codigo, "forma_pagamento": forma_pagamento, "valor": valor,
    })
    assert resp.status_code == 200, resp.text


def _bater_entrada(client):
    resp = client.post("/gestao/ponto/entrada")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------
# Ponto (independente de caixa)
# ---------------------------------------------------------------------
def test_ponto_entrada_cria_registro(client, db_session):
    resp = client.post("/gestao/ponto/entrada")
    assert resp.status_code == 200, resp.text
    assert resp.json()["tipo"] == "entrada"

    ponto = db_session.query(models.RegistroPonto).filter_by(
        unidade_id=UNIDADE_TESTE_ID, tipo=models.TipoRegistroPonto.entrada
    ).first()
    assert ponto is not None
    assert ponto.usuario_nome == "Usuário de Teste"


def test_ponto_entrada_duplicado_sem_saida_e_rejeitado(client):
    _bater_entrada(client)
    resp = client.post("/gestao/ponto/entrada")
    assert resp.status_code == 409


def test_ponto_saida_sem_entrada_e_rejeitado(client):
    resp = client.post("/gestao/ponto/saida")
    assert resp.status_code == 409


def test_ponto_ciclo_completo_entrada_saida_e_nova_entrada(client):
    _bater_entrada(client)
    resp_saida = client.post("/gestao/ponto/saida")
    assert resp_saida.status_code == 200
    assert resp_saida.json()["tipo"] == "saida"

    # depois de bater saída, consegue bater entrada de novo (novo turno)
    resp_nova_entrada = client.post("/gestao/ponto/entrada")
    assert resp_nova_entrada.status_code == 200


def test_intervalo_sem_ponto_de_entrada_e_rejeitado(client):
    resp = client.post("/gestao/ponto/intervalo-inicio")
    assert resp.status_code == 409


def test_intervalo_inicio_e_fim_atualizam_em_intervalo(client):
    _bater_entrada(client)

    resp_inicio = client.post("/gestao/ponto/intervalo-inicio")
    assert resp_inicio.status_code == 200
    assert resp_inicio.json()["tipo"] == "inicio_intervalo"

    resp_atual = client.get("/gestao/caixa/atual")
    assert resp_atual.json()["em_intervalo"] is True

    resp_fim = client.post("/gestao/ponto/intervalo-fim")
    assert resp_fim.status_code == 200
    assert resp_fim.json()["tipo"] == "fim_intervalo"

    resp_atual2 = client.get("/gestao/caixa/atual")
    assert resp_atual2.json()["em_intervalo"] is False


def test_intervalo_inicio_duas_vezes_seguidas_e_rejeitado(client):
    _bater_entrada(client)
    client.post("/gestao/ponto/intervalo-inicio")

    resp = client.post("/gestao/ponto/intervalo-inicio")
    assert resp.status_code == 409


def test_intervalo_fim_sem_inicio_e_rejeitado(client):
    _bater_entrada(client)
    resp = client.post("/gestao/ponto/intervalo-fim")
    assert resp.status_code == 409


# ---------------------------------------------------------------------
# Caixa -- exige ponto de entrada já batido
# ---------------------------------------------------------------------
def test_abrir_caixa_sem_bater_ponto_e_rejeitado(client):
    resp = client.post("/gestao/caixa/abrir")
    assert resp.status_code == 422
    assert "ponto de entrada" in resp.json()["detail"].lower()


def test_abrir_caixa_apos_ponto_de_entrada_funciona(client, db_session):
    _bater_entrada(client)
    resp = client.post("/gestao/caixa/abrir")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["aberto"] is True
    assert data["caixa"]["status"] == "aberto"
    assert data["em_turno"] is True
    assert data["em_intervalo"] is False

    caixa = db_session.query(models.Caixa).filter_by(unidade_id=UNIDADE_TESTE_ID).first()
    assert caixa is not None
    assert caixa.status == models.StatusCaixa.aberto

    # só o /gestao/ponto/entrada que bateu o ponto -- abrir caixa não duplica
    pontos_entrada = db_session.query(models.RegistroPonto).filter_by(
        unidade_id=UNIDADE_TESTE_ID, tipo=models.TipoRegistroPonto.entrada
    ).count()
    assert pontos_entrada == 1


def test_abrir_caixa_com_outro_ja_aberto_e_rejeitado(client):
    _bater_entrada(client)
    resp1 = client.post("/gestao/caixa/abrir")
    assert resp1.status_code == 200

    resp2 = client.post("/gestao/caixa/abrir")
    assert resp2.status_code == 409
    assert "já existe um caixa aberto" in resp2.json()["detail"].lower()


def test_caixa_atual_sem_nenhum_aberto(client):
    resp = client.get("/gestao/caixa/atual")
    assert resp.status_code == 200
    data = resp.json()
    assert data["aberto"] is False
    assert data["caixa"] is None
    assert data["relatorio"] is None
    assert data["em_turno"] is False


def test_caixa_atual_reflete_em_turno_antes_de_abrir_caixa(client):
    _bater_entrada(client)
    resp = client.get("/gestao/caixa/atual")
    assert resp.json()["aberto"] is False
    assert resp.json()["em_turno"] is True


def test_caixa_atual_com_caixa_aberto_mostra_relatorio(client):
    _bater_entrada(client)
    client.post("/gestao/caixa/abrir")
    ticket = client.post("/entrada").json()

    resp = client.get("/gestao/caixa/atual")
    assert resp.status_code == 200
    data = resp.json()
    assert data["aberto"] is True
    assert data["relatorio"]["tickets_estacionados"] == 1
    assert data["relatorio"]["tickets_liberados"] == 0


def test_fechar_caixa_sem_caixa_aberto_e_rejeitado(client):
    resp = client.post("/gestao/caixa/fechar", json={"valor_contado_dinheiro": 100.0})
    assert resp.status_code == 404


def test_fechar_caixa_calcula_diferenca_e_nao_bate_ponto_de_saida(client, db_session):
    _bater_entrada(client)
    client.post("/gestao/caixa/abrir")

    # dois tickets pagos em dinheiro (R$50 no total) durante o turno
    for _ in range(2):
        ticket = client.post("/entrada").json()
        t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
        t.status = models.StatusTicket.tarifado
        t.valor_calculado = 25.0
        db_session.commit()
        _pagar(client, ticket["codigo_barras"], "dinheiro", 25.0)

    # o colaborador contou R$45 (faltou R$5)
    resp = client.post("/gestao/caixa/fechar", json={"valor_contado_dinheiro": 45.0})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["caixa"]["status"] == "fechado"
    assert data["caixa"]["valor_contado_dinheiro"] == 45.0
    assert data["caixa"]["diferenca_dinheiro"] == -5.0
    assert data["relatorio"]["por_forma_pagamento"]["dinheiro"] == 50.0

    # fechar caixa não bate ponto de saída -- isso é um passo separado
    # (POST /gestao/ponto/saida), então não deve existir nenhum registro ainda
    ponto_saida = db_session.query(models.RegistroPonto).filter_by(
        unidade_id=UNIDADE_TESTE_ID, tipo=models.TipoRegistroPonto.saida
    ).first()
    assert ponto_saida is None

    # ainda em turno (só bateu entrada) -- consegue abrir outro caixa em seguida
    resp2 = client.post("/gestao/caixa/abrir")
    assert resp2.status_code == 200


def test_fluxo_completo_entrada_caixa_fechamento_saida(client, db_session):
    """Sequência real do terminal POS: ponto entrada -> abrir caixa ->
    ... -> fechar caixa -> ponto saída."""
    _bater_entrada(client)
    assert client.post("/gestao/caixa/abrir").status_code == 200
    resp_fechar = client.post("/gestao/caixa/fechar", json={"valor_contado_dinheiro": 0.0})
    assert resp_fechar.status_code == 200

    resp_saida = client.post("/gestao/ponto/saida")
    assert resp_saida.status_code == 200
    assert resp_saida.json()["tipo"] == "saida"


def test_fechar_caixa_com_valor_exato_da_diferenca_zero(client):
    _bater_entrada(client)
    client.post("/gestao/caixa/abrir")
    resp = client.post("/gestao/caixa/fechar", json={"valor_contado_dinheiro": 0.0})
    assert resp.status_code == 200
    assert resp.json()["caixa"]["diferenca_dinheiro"] == 0.0


# ---------------------------------------------------------------------
# Relatório de ponto (painel de gestão)
# ---------------------------------------------------------------------
def test_relatorio_ponto_lista_e_filtra_por_tipo(client):
    _bater_entrada(client)
    client.post("/gestao/ponto/intervalo-inicio")
    client.post("/gestao/ponto/intervalo-fim")
    client.post("/gestao/ponto/saida")

    resp_todos = client.get("/gestao/ponto")
    assert resp_todos.status_code == 200
    tipos = [r["tipo"] for r in resp_todos.json()]
    assert tipos == ["saida", "fim_intervalo", "inicio_intervalo", "entrada"]  # mais recente primeiro

    resp_filtrado = client.get("/gestao/ponto?tipo=entrada")
    assert len(resp_filtrado.json()) == 1
    assert resp_filtrado.json()[0]["tipo"] == "entrada"


def test_relatorio_ponto_filtra_por_unidade_diferente_nao_traz_nada(client):
    _bater_entrada(client)
    resp = client.get(f"/gestao/ponto?unidade_id={UNIDADE_TESTE_ID + 1}")
    assert resp.status_code == 200
    # supervisor nunca sai da própria unidade -- escopo_unidade ignora o
    # unidade_id informado e usa a própria, então ainda traz o registro
    assert len(resp.json()) == 1
