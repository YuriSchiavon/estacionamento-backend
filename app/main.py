"""
API do software de controle de acesso do estacionamento (multi-unidade).

Três grupos de endpoints, cada um pensado para ser chamado pelo respectivo
equipamento (via o driver/adapter que você vai escrever para o protocolo
específico do fornecedor escolhido):

  POST /entrada                      -> chamado pelo totem emissor
  POST /loja/validar-cupom           -> chamado pelo totem de autoatendimento
  GET  /saida/verificar/{codigo}     -> chamado pelo totem leitor da cancela
  POST /saida/pagamento              -> chamado pelo totem de pagamento (se houver)

Cada totem loga com seu próprio usuário (ver POST /auth/login em
app/auth.py) e só enxerga/afeta dados da própria unidade -- ver
app/security.py.

Rodar localmente:
  pip install -r requirements.txt
  uvicorn app.main:app --reload
Depois acesse http://localhost:8000/docs para testar tudo pela interface Swagger.
"""
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import models, schemas, services
from .auth import router as auth_router
from .database import Base, engine, get_db
from .migrations import migrar_colunas_novas
from .nfce import extrair_cnpj_emitente
from .qrcode_util import gerar_qr_svg
from .rotas_gestao import router as rotas_gestao_router
from .seed import seed
from .security import (
    exigir_totem_entrada,
    exigir_totem_saida,
    exigir_totem_validacao_ou_saida,
    resolver_unidade_operacional,
)

migrar_colunas_novas(engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Estacionamento - Controle de Acesso")
app.include_router(auth_router)
app.include_router(rotas_gestao_router)

STATIC_DIR = Path(__file__).parent / "static"

# Os totens ficam com a aba aberta por dias/semanas sem recarregar --
# sem isso, o navegador pode servir a página antiga da memória/cache
# indefinidamente mesmo depois de um deploy novo. Força sempre revalidar
# com o servidor (ETag/Last-Modified, que o FileResponse já manda),
# nunca usar uma cópia antiga sem checar primeiro.
_SEM_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


@app.on_event("startup")
def startup():
    seed()


@app.get("/", include_in_schema=False)
def pagina_inicial():
    """Landing: links para o painel de gestão, operação e totens."""
    return FileResponse(STATIC_DIR / "inicio.html", headers=_SEM_CACHE)


@app.get("/gestao", include_in_schema=False)
def painel_de_gestao():
    """Painel de gestão: credenciados/mensalistas e relatórios."""
    return FileResponse(STATIC_DIR / "gestao.html", headers=_SEM_CACHE)


@app.get("/operacao", include_in_schema=False)
def pagina_operacao():
    """Login único de operador + ações do dia a dia (estacionamento assistido)."""
    return FileResponse(STATIC_DIR / "operacao.html", headers=_SEM_CACHE)


@app.get("/totem/entrada", include_in_schema=False)
def pagina_totem_entrada():
    """Tela real do totem de entrada: um botão, emite o ticket."""
    return FileResponse(STATIC_DIR / "totem_entrada.html", headers=_SEM_CACHE)


@app.get("/totem/saida", include_in_schema=False)
def pagina_totem_saida():
    """Tela real do totem de saída: leitura do ticket + revalidação de cupom."""
    return FileResponse(STATIC_DIR / "totem_saida.html", headers=_SEM_CACHE)


@app.get("/totem/validacao", include_in_schema=False)
def pagina_totem_validacao():
    """Tela real do totem de validação/pagamento -- sem controle de cancela."""
    return FileResponse(STATIC_DIR / "totem_validacao.html", headers=_SEM_CACHE)


@app.get("/simulador-totens", include_in_schema=False)
def pagina_simulador():
    """Simulador dos 5 totens numa página só, para testar sem hardware."""
    return FileResponse(STATIC_DIR / "simulador.html", headers=_SEM_CACHE)


# ---------------------------------------------------------------------
# ENTRADA — chamado pelo totem emissor quando o botão é pressionado
# ---------------------------------------------------------------------
@app.post("/entrada", response_model=schemas.TicketOut)
def registrar_entrada(
    gate_entrada: str = "entrada-1",
    unidade_id: Optional[int] = None,
    pre_pago: bool = False,
    forma_pagamento: Optional[Literal["pix", "credito", "debito"]] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_totem_entrada),
):
    unidade_id_resolvida = resolver_unidade_operacional(db, usuario, unidade_id)
    unidade = db.get(models.Unidade, unidade_id_resolvida)

    # Pré-pagamento por preço fixo -- opção extra da unidade (ver
    # GET /gestao/unidades/{id}/config-totem). Nunca confia só no
    # cliente: reconfirma no servidor que a unidade permite, mesmo
    # padrão da checagem de valor de pagamento na saída.
    if pre_pago:
        if not unidade.permite_pre_pagamento:
            raise HTTPException(422, "Esta unidade não permite pré-pagamento por preço fixo")
        if not forma_pagamento:
            raise HTTPException(422, "Informe a forma de pagamento para o pré-pagamento")

    ticket = models.Ticket(unidade_id=unidade_id_resolvida, gate_entrada=gate_entrada, pre_pago=pre_pago)
    db.add(ticket)
    db.flush()
    if pre_pago:
        db.add(models.Transacao(
            ticket_id=ticket.id, forma_pagamento=forma_pagamento, valor=unidade.valor_pre_pagamento,
        ))
    db.commit()
    db.refresh(ticket)
    # Aqui é onde o driver do totem deve:
    #   1) mandar o comando de impressão com ticket.codigo_barras
    #   2) esperar confirmação de retirada
    #   3) só então mandar o comando de abertura da cancela de entrada
    resposta = schemas.TicketOut.model_validate(ticket)
    # QR code do código do ticket -- só aqui, pra poder ser lido direto
    # pelo scanner no totem de saída/validação, sem precisar digitar.
    resposta.qr_code_svg = gerar_qr_svg(ticket.codigo_barras)
    resposta.ticket_texto_extra = unidade.ticket_texto_extra
    resposta.imprimir_automaticamente = unidade.imprimir_automaticamente
    return resposta


# ---------------------------------------------------------------------
# LOJA — chamado pelo totem de autoatendimento após ler o QR code da NFC-e.
# Também aceita o totem de saída (e operador): "revalidação" -- se o
# cliente chegou na cancela sem ter validado o cupom na loja, dá pra
# validar ali mesmo. Funciona tanto antes de /saida/verificar rodar
# (status ainda "aberto") quanto depois, se o ticket ficou "tarifado" --
# nesse caso o totem deve chamar /saida/verificar de novo em seguida para
# recalcular a tolerância com o cupom já vinculado.
# ---------------------------------------------------------------------
@app.post("/loja/validar-cupom", response_model=schemas.TicketOut)
def validar_cupom(
    payload: schemas.ValidarCupomRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_totem_validacao_ou_saida),
):
    unidade_id = resolver_unidade_operacional(db, usuario, payload.unidade_id)
    ticket = db.query(models.Ticket).filter_by(
        codigo_barras=payload.codigo_barras, unidade_id=unidade_id
    ).first()
    if not ticket:
        raise HTTPException(404, "Ticket não encontrado")
    # "aberto" é o caso normal (loja, antes da saída); "tarifado" é a
    # revalidação no totem de saída -- já rodou /saida/verificar e excedeu
    # a tolerância, mas o cliente ainda pode apresentar o cupom ali mesmo,
    # antes de pagar. Qualquer outro status (finalizado/pago) já saiu.
    if ticket.status not in (models.StatusTicket.aberto, models.StatusTicket.tarifado):
        raise HTTPException(409, f"Ticket não pode receber cupom (status atual: {ticket.status})")

    ja_usado = db.query(models.CupomFiscal).filter_by(
        chave_acesso_nfce=payload.chave_acesso_nfce
    ).first()
    if ja_usado:
        db.add(models.TentativaCupomDuplicado(
            unidade_id=unidade_id,
            chave_acesso_nfce=payload.chave_acesso_nfce,
            codigo_barras_tentativa=payload.codigo_barras,
            ticket_original_id=ja_usado.ticket_id,
        ))
        db.commit()
        raise HTTPException(409, "Este cupom fiscal já foi validado em outro ticket")

    try:
        cnpj = extrair_cnpj_emitente(payload.chave_acesso_nfce)
    except ValueError as erro:
        raise HTTPException(422, str(erro))

    estabelecimento = db.query(models.Estabelecimento).filter_by(
        cnpj=cnpj, unidade_id=unidade_id, ativo=True
    ).first()
    if not estabelecimento:
        raise HTTPException(
            403,
            "Este cupom não é de um estabelecimento conveniado desta unidade -- não conta para tolerância",
        )

    cupom = models.CupomFiscal(
        chave_acesso_nfce=payload.chave_acesso_nfce,
        cnpj_estabelecimento=cnpj,
        estabelecimento_id=estabelecimento.id,
        valor_compra=payload.valor_compra,
        data_hora_emissao=payload.data_hora_emissao,
        ticket_id=ticket.id,
    )
    db.add(cupom)
    db.commit()
    db.refresh(ticket)

    # Não decide status aqui -- a checagem de tolerância só é definitiva
    # no momento da saída, pois depende do tempo de permanência total.
    return ticket


# ---------------------------------------------------------------------
# SAÍDA — chamado pelo totem leitor da cancela quando o ticket é apresentado
# ---------------------------------------------------------------------
@app.get("/saida/verificar/{codigo_barras}", response_model=schemas.VerificarSaidaResponse)
def verificar_saida(
    codigo_barras: str,
    unidade_id: Optional[int] = None,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_totem_saida),
):
    unidade_id_resolvida = resolver_unidade_operacional(db, usuario, unidade_id)
    ticket = db.query(models.Ticket).filter_by(
        codigo_barras=codigo_barras, unidade_id=unidade_id_resolvida
    ).first()
    if not ticket:
        raise HTTPException(404, "Ticket não encontrado")
    if ticket.status == models.StatusTicket.finalizado:
        raise HTTPException(409, "Este ticket já foi utilizado para sair")

    liberar, motivo = services.processar_saida(db, ticket)

    return schemas.VerificarSaidaResponse(
        codigo_barras=ticket.codigo_barras,
        liberar_cancela=liberar,
        motivo=motivo,
        tempo_permanencia_minutos=ticket.tempo_permanencia_minutos,
        tolerancia_aplicada_minutos=ticket.tolerancia_aplicada_minutos,
        valor_calculado=ticket.valor_calculado,
    )


# ---------------------------------------------------------------------
# PAGAMENTO — chamado pelo totem de pagamento quando o ticket está tarifado
# ---------------------------------------------------------------------
@app.post("/saida/pagamento", response_model=schemas.TicketOut)
def registrar_pagamento(
    payload: schemas.PagamentoRequest,
    db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_totem_saida),
):
    unidade_id = resolver_unidade_operacional(db, usuario, payload.unidade_id)
    ticket = db.query(models.Ticket).filter_by(
        codigo_barras=payload.codigo_barras, unidade_id=unidade_id
    ).first()
    if not ticket:
        raise HTTPException(404, "Ticket não encontrado")
    if ticket.status != models.StatusTicket.tarifado:
        raise HTTPException(409, f"Ticket não está aguardando pagamento (status: {ticket.status})")
    # Nunca confia no valor que o totem manda pra decidir se o ticket foi
    # pago -- o valor de verdade é o que o próprio backend calculou em
    # /saida/verificar. Sem essa checagem, um totem comprometido (ou um
    # bug de frontend) poderia "pagar" qualquer valor e liberar a cancela.
    # Tolerância de 1 centavo pra arredondamento de ponto flutuante;
    # sobrepagamento (troco/gorjeta) é permitido, subpagamento não.
    if payload.valor < ticket.valor_calculado - 0.01:
        raise HTTPException(
            422,
            f"Valor informado (R$ {payload.valor:.2f}) é menor que o valor devido "
            f"(R$ {ticket.valor_calculado:.2f})",
        )

    transacao = models.Transacao(
        ticket_id=ticket.id,
        forma_pagamento=payload.forma_pagamento,
        valor=payload.valor,
    )
    db.add(transacao)
    ticket.status = models.StatusTicket.pago
    db.commit()
    db.refresh(ticket)
    return ticket
