"""
API do software de controle de acesso do estacionamento.

Três grupos de endpoints, cada um pensado para ser chamado pelo respectivo
equipamento (via o driver/adapter que você vai escrever para o protocolo
específico do fornecedor escolhido):

  POST /entrada                      -> chamado pelo totem emissor
  POST /loja/validar-cupom           -> chamado pelo totem de autoatendimento
  GET  /saida/verificar/{codigo}     -> chamado pelo totem leitor da cancela
  POST /saida/pagamento              -> chamado pelo totem de pagamento (se houver)

Rodar localmente:
  pip install -r requirements.txt
  uvicorn app.main:app --reload
Depois acesse http://localhost:8000/docs para testar tudo pela interface Swagger.
"""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import models, schemas, services
from .database import Base, engine, get_db
from .rotas_gestao import router as rotas_gestao_router
from .seed import seed
from .security import chaves_ainda_no_padrao_dev, exigir_chave_entrada, exigir_chave_saida, exigir_chave_validacao

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Estacionamento - Controle de Acesso")
app.include_router(rotas_gestao_router)

STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
def startup():
    seed()
    pendentes = chaves_ainda_no_padrao_dev()
    if pendentes:
        print(
            f"AVISO: totem(s) {', '.join(pendentes)} ainda usando chave de API "
            f"padrão de desenvolvimento -- troque no .env antes de ir para produção."
        )


@app.get("/", include_in_schema=False)
def painel_de_testes():
    """Painel visual para testar o fluxo sem precisar do Swagger."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/gestao", include_in_schema=False)
def painel_de_gestao():
    """Painel de gestão: credenciados/mensalistas e relatórios."""
    return FileResponse(STATIC_DIR / "gestao.html")


# ---------------------------------------------------------------------
# ENTRADA — chamado pelo totem emissor quando o botão é pressionado
# ---------------------------------------------------------------------
@app.post("/entrada", response_model=schemas.TicketOut, dependencies=[Depends(exigir_chave_entrada)])
def registrar_entrada(gate_entrada: str = "entrada-1", db: Session = Depends(get_db)):
    ticket = models.Ticket(gate_entrada=gate_entrada)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    # Aqui é onde o driver do totem deve:
    #   1) mandar o comando de impressão com ticket.codigo_barras
    #   2) esperar confirmação de retirada
    #   3) só então mandar o comando de abertura da cancela de entrada
    return ticket


# ---------------------------------------------------------------------
# LOJA — chamado pelo totem de autoatendimento após ler o QR code da NFC-e
# ---------------------------------------------------------------------
@app.post("/loja/validar-cupom", response_model=schemas.TicketOut, dependencies=[Depends(exigir_chave_validacao)])
def validar_cupom(payload: schemas.ValidarCupomRequest, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).filter_by(codigo_barras=payload.codigo_barras).first()
    if not ticket:
        raise HTTPException(404, "Ticket não encontrado")
    if ticket.status != models.StatusTicket.aberto:
        raise HTTPException(409, f"Ticket não está aberto (status atual: {ticket.status})")

    ja_usado = db.query(models.CupomFiscal).filter_by(
        chave_acesso_nfce=payload.chave_acesso_nfce
    ).first()
    if ja_usado:
        db.add(models.TentativaCupomDuplicado(
            chave_acesso_nfce=payload.chave_acesso_nfce,
            codigo_barras_tentativa=payload.codigo_barras,
            ticket_original_id=ja_usado.ticket_id,
        ))
        db.commit()
        raise HTTPException(409, "Este cupom fiscal já foi validado em outro ticket")

    cupom = models.CupomFiscal(
        chave_acesso_nfce=payload.chave_acesso_nfce,
        cnpj_estabelecimento=payload.cnpj_estabelecimento,
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
@app.get("/saida/verificar/{codigo_barras}", response_model=schemas.VerificarSaidaResponse, dependencies=[Depends(exigir_chave_saida)])
def verificar_saida(codigo_barras: str, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).filter_by(codigo_barras=codigo_barras).first()
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
@app.post("/saida/pagamento", response_model=schemas.TicketOut, dependencies=[Depends(exigir_chave_saida)])
def registrar_pagamento(payload: schemas.PagamentoRequest, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).filter_by(codigo_barras=payload.codigo_barras).first()
    if not ticket:
        raise HTTPException(404, "Ticket não encontrado")
    if ticket.status != models.StatusTicket.tarifado:
        raise HTTPException(409, f"Ticket não está aguardando pagamento (status: {ticket.status})")

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
