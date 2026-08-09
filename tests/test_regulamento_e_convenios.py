"""
Cobre a aba Regulamento (tarifa/granularidade por unidade, pré-pagamento
por preço fixo) e o convênio do tipo desconto_percentual (% de desconto
na tarifa, válido só até um número fixo de horas).
"""
from datetime import timedelta

from app import models
from app.auth import gerar_hash_senha
from app.tempo import agora_utc
from tests.conftest import UNIDADE_TESTE_ID, fabricar_chave_nfce


CNPJ_CONVENIO_DESCONTO = "22333444000155"


def _criar_convenio_desconto(db_session, percentual_desconto=20, horas_fixas=2, valor_minimo_compra=0.01):
    estabelecimento = models.Estabelecimento(
        unidade_id=UNIDADE_TESTE_ID, cnpj=CNPJ_CONVENIO_DESCONTO, nome="Convênio Desconto",
        tipo_beneficio=models.TipoBeneficioConvenio.desconto_percentual,
    )
    db_session.add(estabelecimento)
    db_session.flush()
    db_session.add(models.RegraDesconto(
        estabelecimento_id=estabelecimento.id, valor_minimo_compra=valor_minimo_compra,
        percentual_desconto=percentual_desconto, horas_fixas=horas_fixas,
    ))
    db_session.commit()
    return estabelecimento


def _emitir_e_envelhecer(client, db_session, minutos):
    ticket = client.post("/entrada").json()
    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=minutos)
    db_session.commit()
    return ticket["codigo_barras"]


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


# ---------------------------------------------------------------------
# Convênio de desconto percentual
# ---------------------------------------------------------------------
def test_desconto_percentual_aplicado_dentro_das_horas_fixas(client, db_session):
    _criar_convenio_desconto(db_session, percentual_desconto=20, horas_fixas=2)
    codigo = _emitir_e_envelhecer(client, db_session, 90)  # 1h30, dentro das 2h fixas

    client.post("/loja/validar-cupom", json={
        "codigo_barras": codigo,
        "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_CONVENIO_DESCONTO, sufixo=1),
        "valor_compra": 20.0,
    })
    resp = client.get(f"/saida/verificar/{codigo}")
    assert resp.status_code == 200
    data = resp.json()
    # sem desconto seria 15.0 (2 horas: 10 + 5); com 20% de desconto: 12.0
    assert data["valor_calculado"] == 12.0
    assert data["liberar_cancela"] is False


def test_desconto_percentual_nao_aplica_alem_das_horas_fixas(client, db_session):
    _criar_convenio_desconto(db_session, percentual_desconto=20, horas_fixas=2)
    codigo = _emitir_e_envelhecer(client, db_session, 150)  # 2h30, além das 2h fixas

    client.post("/loja/validar-cupom", json={
        "codigo_barras": codigo,
        "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_CONVENIO_DESCONTO, sufixo=2),
        "valor_compra": 20.0,
    })
    resp = client.get(f"/saida/verificar/{codigo}")
    assert resp.status_code == 200
    # sem desconto (excedeu as horas fixas da regra): 3 horas = 10 + 5*2 = 20.0
    assert resp.json()["valor_calculado"] == 20.0


def test_desconto_percentual_nao_da_minutos_gratis(client, db_session):
    """Diferente do convênio de tolerância, o de desconto não isenta --
    só desconta a tarifa depois de excedida a tolerância padrão da
    unidade (15 min, no fixture de teste)."""
    _criar_convenio_desconto(db_session, percentual_desconto=50, horas_fixas=6)
    codigo = _emitir_e_envelhecer(client, db_session, 20)  # excede a tolerância padrão de 15 min

    client.post("/loja/validar-cupom", json={
        "codigo_barras": codigo,
        "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_CONVENIO_DESCONTO, sufixo=3),
        "valor_compra": 20.0,
    })
    resp = client.get(f"/saida/verificar/{codigo}")
    assert resp.json()["liberar_cancela"] is False  # não é isento, mesmo com o convênio


# ---------------------------------------------------------------------
# Tarifa e granularidade configuráveis por unidade
# ---------------------------------------------------------------------
def test_tarifa_customizada_por_unidade_reflete_na_saida(client, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=UNIDADE_TESTE_ID).first()
    unidade.valor_primeira_hora = 20.0
    unidade.incremento_por_hora = 8.0
    unidade.valor_diaria = 60.0
    db_session.commit()

    codigo = _emitir_e_envelhecer(client, db_session, 90)  # 2h (arredonda pra cima)
    resp = client.get(f"/saida/verificar/{codigo}")
    assert resp.json()["valor_calculado"] == 28.0  # 20 + 8


def test_granularidade_fracao_15min_cobra_proporcional(client, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=UNIDADE_TESTE_ID).first()
    unidade.granularidade_cobranca = models.GranularidadeCobranca.fracao_15min
    db_session.commit()

    codigo = _emitir_e_envelhecer(client, db_session, 20)  # 5 min além da tolerância de 15
    resp = client.get(f"/saida/verificar/{codigo}")
    # 20 min = 2 blocos de 15 -- 2 * (10/4) = 5.0, bem menor que a hora cheia (10.0)
    assert resp.json()["valor_calculado"] == 5.0


def test_regulamento_salva_via_patch_unidade(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    resp = client_com_autenticacao_real.patch(
        f"/gestao/unidades/{UNIDADE_TESTE_ID}", headers=_auth(token),
        json={
            "valor_primeira_hora": 12.0, "incremento_por_hora": 6.0, "valor_diaria": 40.0,
            "granularidade_cobranca": "fracao_15min", "funcionamento_24h": False,
            "ticket_texto_extra": "Não nos responsabilizamos por objetos no veículo",
            "imprimir_automaticamente": False,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valor_primeira_hora"] == 12.0
    assert data["granularidade_cobranca"] == "fracao_15min"
    assert data["funcionamento_24h"] is False
    assert data["imprimir_automaticamente"] is False


# ---------------------------------------------------------------------
# Pré-pagamento por preço fixo
# ---------------------------------------------------------------------
def test_pre_pagamento_bloqueado_quando_unidade_nao_permite(client):
    resp = client.post("/entrada", params={"pre_pago": True, "forma_pagamento": "pix"})
    assert resp.status_code == 422


def test_pre_pagamento_funciona_de_ponta_a_ponta_quando_permitido(client, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=UNIDADE_TESTE_ID).first()
    unidade.permite_pre_pagamento = True
    unidade.valor_pre_pagamento = 25.0
    db_session.commit()

    resp = client.post("/entrada", params={"pre_pago": True, "forma_pagamento": "pix"})
    assert resp.status_code == 200
    ticket = resp.json()

    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    assert t.pre_pago is True
    assert len(t.transacoes) == 1
    assert t.transacoes[0].valor == 25.0

    # envelhece bem além de qualquer tolerância -- mesmo assim libera,
    # porque já foi pago fixo na entrada
    t.data_hora_entrada = agora_utc() - timedelta(hours=10)
    db_session.commit()
    verificacao = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    assert verificacao.status_code == 200
    assert verificacao.json()["liberar_cancela"] is True
    assert verificacao.json()["motivo"] == "Pré-pago na entrada"


def test_pre_pagamento_exige_forma_de_pagamento(client, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=UNIDADE_TESTE_ID).first()
    unidade.permite_pre_pagamento = True
    unidade.valor_pre_pagamento = 25.0
    db_session.commit()

    resp = client.post("/entrada", params={"pre_pago": True})
    assert resp.status_code == 422


# ---------------------------------------------------------------------
# GET config-totem -- não exige exigir_gestao, só login
# ---------------------------------------------------------------------
def test_config_totem_acessivel_por_conta_de_totem(client_com_autenticacao_real, db_session):
    unidade = db_session.query(models.Unidade).filter_by(id=UNIDADE_TESTE_ID).first()
    unidade.permite_pre_pagamento = True
    unidade.valor_pre_pagamento = 30.0
    db_session.commit()

    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=UNIDADE_TESTE_ID)
    token = _login(client_com_autenticacao_real, "entrada1")

    resp = client_com_autenticacao_real.get(
        f"/gestao/unidades/{UNIDADE_TESTE_ID}/config-totem", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["permite_pre_pagamento"] is True
    assert resp.json()["valor_pre_pagamento"] == 30.0
