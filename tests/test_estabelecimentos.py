"""
Cobre o cadastro de estabelecimentos conveniados e a validação de cupom
fiscal contra o CNPJ embutido na chave de acesso da NFC-e -- cada
estabelecimento tem seu próprio regulamento de tolerância (contratos
diferentes não compartilham tabela).
"""
from app.auth import gerar_hash_senha
from app import models
from tests.conftest import CNPJ_ESTABELECIMENTO_TESTE, fabricar_chave_nfce

CNPJ_NAO_CONVENIADO = "99888777000166"


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


def test_cadastrar_estabelecimento(client):
    resp = client.post("/gestao/estabelecimentos", json={
        "cnpj": "22333444000155",
        "nome": "Loja Parceira do Shopping",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["nome"] == "Loja Parceira do Shopping"
    assert data["ativo"] is True
    assert data["regras_tolerancia"] == []


def test_cnpj_com_formato_invalido_e_rejeitado(client):
    resp = client.post("/gestao/estabelecimentos", json={
        "cnpj": "123",
        "nome": "CNPJ curto demais",
    })
    assert resp.status_code == 422


def test_cnpj_duplicado_e_rejeitado(client):
    payload = {"cnpj": "22333444000155", "nome": "Primeira"}
    client.post("/gestao/estabelecimentos", json=payload)
    resp = client.post("/gestao/estabelecimentos", json={**payload, "nome": "Segunda"})
    assert resp.status_code == 409


def test_desativar_estabelecimento(client):
    criado = client.post("/gestao/estabelecimentos", json={
        "cnpj": "22333444000155", "nome": "Loja X",
    }).json()

    resp = client.patch(f"/gestao/estabelecimentos/{criado['id']}", json={"ativo": False})
    assert resp.status_code == 200
    assert resp.json()["ativo"] is False


def test_excluir_estabelecimento_sem_cupons_funciona(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    token = _login(client_com_autenticacao_real, "dono1")

    criado = client_com_autenticacao_real.post(
        "/gestao/estabelecimentos", headers=_auth(token),
        json={"cnpj": "22333444000155", "nome": "Loja X", "unidade_id": 1},
    ).json()
    client_com_autenticacao_real.post(
        f"/gestao/estabelecimentos/{criado['id']}/regras-tolerancia", headers=_auth(token),
        json={"valor_minimo_compra": 20.0, "tolerancia_minutos": 45},
    )

    resp = client_com_autenticacao_real.delete(f"/gestao/estabelecimentos/{criado['id']}", headers=_auth(token))
    assert resp.status_code == 200

    lista = client_com_autenticacao_real.get("/gestao/estabelecimentos", headers=_auth(token)).json()
    assert all(e["id"] != criado["id"] for e in lista)


def test_excluir_estabelecimento_com_cupom_validado_e_rejeitado(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "dono1", models.PapelUsuario.dono)
    _criar_usuario(db_session, "entrada1", models.PapelUsuario.totem_entrada, unidade_id=1)
    _criar_usuario(db_session, "validacao1", models.PapelUsuario.totem_validacao, unidade_id=1)
    token = _login(client_com_autenticacao_real, "dono1")

    criado = client_com_autenticacao_real.post(
        "/gestao/estabelecimentos", headers=_auth(token),
        json={"cnpj": "22333444000155", "nome": "Loja X", "unidade_id": 1},
    ).json()

    token_entrada = _login(client_com_autenticacao_real, "entrada1")
    ticket = client_com_autenticacao_real.post("/entrada", headers=_auth(token_entrada)).json()
    token_validacao = _login(client_com_autenticacao_real, "validacao1")
    client_com_autenticacao_real.post(
        "/loja/validar-cupom", headers=_auth(token_validacao),
        json={
            "codigo_barras": ticket["codigo_barras"],
            "chave_acesso_nfce": fabricar_chave_nfce("22333444000155", sufixo=1),
            "valor_compra": 50.0,
        },
    )

    resp = client_com_autenticacao_real.delete(f"/gestao/estabelecimentos/{criado['id']}", headers=_auth(token))
    assert resp.status_code == 409


def test_gerente_nao_pode_excluir_estabelecimento(client_com_autenticacao_real, db_session):
    _criar_usuario(db_session, "gerente1", models.PapelUsuario.supervisor, unidade_id=1)
    token = _login(client_com_autenticacao_real, "gerente1")

    criado = client_com_autenticacao_real.post(
        "/gestao/estabelecimentos", headers=_auth(token), json={"cnpj": "22333444000155", "nome": "Loja X"},
    ).json()

    resp = client_com_autenticacao_real.delete(f"/gestao/estabelecimentos/{criado['id']}", headers=_auth(token))
    assert resp.status_code == 403


def test_adicionar_e_remover_regra_tolerancia(client):
    criado = client.post("/gestao/estabelecimentos", json={
        "cnpj": "22333444000155", "nome": "Loja X",
    }).json()

    adicionada = client.post(
        f"/gestao/estabelecimentos/{criado['id']}/regras-tolerancia",
        json={"valor_minimo_compra": 20.0, "tolerancia_minutos": 45},
    )
    assert adicionada.status_code == 200
    regras = adicionada.json()["regras_tolerancia"]
    assert len(regras) == 1
    regra_id = regras[0]["id"]

    removida = client.delete(
        f"/gestao/estabelecimentos/{criado['id']}/regras-tolerancia/{regra_id}"
    )
    assert removida.status_code == 200
    assert removida.json()["regras_tolerancia"] == []


def test_regra_com_mesmo_valor_minimo_duplicada_e_rejeitada(client):
    criado = client.post("/gestao/estabelecimentos", json={
        "cnpj": "22333444000155", "nome": "Loja X",
    }).json()
    payload = {"valor_minimo_compra": 20.0, "tolerancia_minutos": 45}
    client.post(f"/gestao/estabelecimentos/{criado['id']}/regras-tolerancia", json=payload)

    resp = client.post(f"/gestao/estabelecimentos/{criado['id']}/regras-tolerancia", json=payload)
    assert resp.status_code == 409


def test_cupom_de_estabelecimento_nao_conveniado_e_rejeitado(client):
    ticket = _emitir_ticket(client)
    resp = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket["codigo_barras"],
        "chave_acesso_nfce": fabricar_chave_nfce(CNPJ_NAO_CONVENIADO, sufixo=1),
        "valor_compra": 50.0,
    })
    assert resp.status_code == 403


def test_cupom_de_estabelecimento_inativo_e_rejeitado(client):
    criado = client.post("/gestao/estabelecimentos", json={
        "cnpj": "22333444000155", "nome": "Loja X",
    }).json()
    client.patch(f"/gestao/estabelecimentos/{criado['id']}", json={"ativo": False})

    ticket = _emitir_ticket(client)
    resp = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket["codigo_barras"],
        "chave_acesso_nfce": fabricar_chave_nfce("22333444000155", sufixo=1),
        "valor_compra": 50.0,
    })
    assert resp.status_code == 403


def test_chave_com_formato_invalido_e_rejeitada(client):
    ticket = _emitir_ticket(client)
    resp = client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket["codigo_barras"],
        "chave_acesso_nfce": "chave-nao-numerica-de-qualquer-tamanho",
        "valor_compra": 50.0,
    })
    assert resp.status_code == 422


def test_tolerancia_usa_regras_do_estabelecimento_correto(client, db_session):
    from datetime import timedelta
    from app import models
    from app.tempo import agora_utc

    # Segundo estabelecimento com regra bem diferente da do estabelecimento
    # de teste padrão (30 min para qualquer cupom) -- 120 min pra qualquer cupom.
    outro = client.post("/gestao/estabelecimentos", json={
        "cnpj": "22333444000155", "nome": "Loja com regulamento próprio",
    }).json()
    client.post(f"/gestao/estabelecimentos/{outro['id']}/regras-tolerancia", json={
        "valor_minimo_compra": 0.01, "tolerancia_minutos": 120,
    })

    ticket = _emitir_ticket(client)
    client.post("/loja/validar-cupom", json={
        "codigo_barras": ticket["codigo_barras"],
        "chave_acesso_nfce": fabricar_chave_nfce("22333444000155", sufixo=1),
        "valor_compra": 10.0,
    })

    t = db_session.query(models.Ticket).filter_by(codigo_barras=ticket["codigo_barras"]).first()
    t.data_hora_entrada = agora_utc() - timedelta(minutes=100)
    db_session.commit()

    resp = client.get(f"/saida/verificar/{ticket['codigo_barras']}")
    data = resp.json()
    assert data["tolerancia_aplicada_minutos"] == 120  # regra do outro estabelecimento, não 30
    assert data["liberar_cancela"] is True
