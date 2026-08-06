"""
Rotas de gestão (cadastro de credenciados/mensalistas, relatórios) e do
fluxo de acesso por reconhecimento facial nos totens de entrada/saída.

Autenticação:
- /credenciados/entrada e /credenciados/saida usam a mesma chave do totem
  de entrada/saída do fluxo normal de ticket (é o mesmo equipamento físico).
- /gestao/* usa uma chave própria (API_KEY_GESTAO), pensada para o painel
  administrativo -- não deve ser configurada em nenhum totem.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import credenciamento, models, schemas
from .database import get_db
from .security import exigir_chave_entrada, exigir_chave_gestao, exigir_chave_saida
from .tempo import agora_utc

router = APIRouter()


# ---------------------------------------------------------------------
# ACESSO POR RECONHECIMENTO FACIAL -- chamado pelos totens de entrada/saída
# ---------------------------------------------------------------------
@router.post(
    "/credenciados/entrada",
    response_model=schemas.AcessoCredenciadoResponse,
    dependencies=[Depends(exigir_chave_entrada)],
)
def entrada_por_reconhecimento_facial(payload: schemas.IdentificacaoFacialRequest, db: Session = Depends(get_db)):
    credenciado = credenciamento.buscar_credenciado_ativo(db, payload.identificador_facial)
    if not credenciado:
        raise HTTPException(404, "Nenhum credenciado ativo encontrado para esse identificador facial")

    ja_aberto = db.query(models.Ticket).filter_by(
        credenciado_id=credenciado.id, data_hora_saida=None
    ).first()
    if ja_aberto:
        raise HTTPException(409, "Este credenciado já possui uma entrada em aberto")

    liberar, motivo = credenciamento.acesso_liberado(credenciado)
    if not liberar:
        return schemas.AcessoCredenciadoResponse(
            liberar_cancela=False, motivo=motivo,
            credenciado_nome=credenciado.nome, tipo=credenciado.tipo,
        )

    ticket = models.Ticket(
        credenciado_id=credenciado.id,
        status=models.StatusTicket.isento,
        valor_calculado=0.0,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return schemas.AcessoCredenciadoResponse(
        liberar_cancela=True, motivo=motivo,
        credenciado_nome=credenciado.nome, tipo=credenciado.tipo, ticket_id=ticket.id,
    )


@router.post(
    "/credenciados/saida",
    response_model=schemas.AcessoCredenciadoResponse,
    dependencies=[Depends(exigir_chave_saida)],
)
def saida_por_reconhecimento_facial(payload: schemas.IdentificacaoFacialRequest, db: Session = Depends(get_db)):
    credenciado = credenciamento.buscar_credenciado_ativo(db, payload.identificador_facial)
    if not credenciado:
        raise HTTPException(404, "Nenhum credenciado ativo encontrado para esse identificador facial")

    ticket = db.query(models.Ticket).filter_by(
        credenciado_id=credenciado.id, data_hora_saida=None
    ).order_by(models.Ticket.id.desc()).first()
    if not ticket:
        raise HTTPException(404, "Nenhuma entrada em aberto para esse credenciado")

    ticket.data_hora_saida = agora_utc()
    ticket.status = models.StatusTicket.finalizado
    db.commit()

    return schemas.AcessoCredenciadoResponse(
        liberar_cancela=True, motivo="Saída liberada",
        credenciado_nome=credenciado.nome, tipo=credenciado.tipo, ticket_id=ticket.id,
    )


# ---------------------------------------------------------------------
# CADASTRO DE CREDENCIADOS/MENSALISTAS -- painel de gestão
# ---------------------------------------------------------------------
@router.post(
    "/gestao/credenciados",
    response_model=schemas.CredenciadoOut,
    dependencies=[Depends(exigir_chave_gestao)],
)
def criar_credenciado(payload: schemas.CredenciadoIn, db: Session = Depends(get_db)):
    existente = db.query(models.Credenciado).filter_by(
        identificador_facial=payload.identificador_facial
    ).first()
    if existente:
        raise HTTPException(409, "Já existe um credenciado com esse identificador facial")

    credenciado = models.Credenciado(**payload.model_dump())
    db.add(credenciado)
    db.commit()
    db.refresh(credenciado)
    return credenciado


@router.get(
    "/gestao/credenciados",
    response_model=List[schemas.CredenciadoOut],
    dependencies=[Depends(exigir_chave_gestao)],
)
def listar_credenciados(db: Session = Depends(get_db)):
    return db.query(models.Credenciado).order_by(models.Credenciado.nome).all()


@router.patch(
    "/gestao/credenciados/{credenciado_id}",
    response_model=schemas.CredenciadoOut,
    dependencies=[Depends(exigir_chave_gestao)],
)
def atualizar_credenciado(credenciado_id: int, payload: schemas.CredenciadoUpdate, db: Session = Depends(get_db)):
    credenciado = db.get(models.Credenciado, credenciado_id)
    if not credenciado:
        raise HTTPException(404, "Credenciado não encontrado")

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(credenciado, campo, valor)

    db.commit()
    db.refresh(credenciado)
    return credenciado


@router.post(
    "/gestao/credenciados/{credenciado_id}/renovar",
    response_model=schemas.CredenciadoOut,
    dependencies=[Depends(exigir_chave_gestao)],
)
def renovar_mensalidade(credenciado_id: int, payload: schemas.RenovarMensalidadeRequest, db: Session = Depends(get_db)):
    credenciado = db.get(models.Credenciado, credenciado_id)
    if not credenciado:
        raise HTTPException(404, "Credenciado não encontrado")
    if credenciado.tipo != models.TipoCredenciado.mensalista:
        raise HTTPException(409, "Renovação de mensalidade só se aplica a mensalistas")

    credenciamento.renovar_mensalidade(db, credenciado, payload.valor, payload.forma_pagamento)
    return credenciado


# ---------------------------------------------------------------------
# RELATÓRIOS -- painel de gestão
# ---------------------------------------------------------------------
@router.get(
    "/gestao/relatorio/tickets",
    response_model=List[schemas.TicketOut],
    dependencies=[Depends(exigir_chave_gestao)],
)
def relatorio_tickets(inicio: Optional[datetime] = None, fim: Optional[datetime] = None, db: Session = Depends(get_db)):
    query = db.query(models.Ticket)
    if inicio:
        query = query.filter(models.Ticket.data_hora_entrada >= inicio)
    if fim:
        query = query.filter(models.Ticket.data_hora_entrada <= fim)
    return query.order_by(models.Ticket.data_hora_entrada.desc()).all()


@router.get(
    "/gestao/relatorio/financeiro",
    response_model=schemas.RelatorioFinanceiroResponse,
    dependencies=[Depends(exigir_chave_gestao)],
)
def relatorio_financeiro(inicio: Optional[datetime] = None, fim: Optional[datetime] = None, db: Session = Depends(get_db)):
    query = db.query(models.Transacao)
    if inicio:
        query = query.filter(models.Transacao.data_hora >= inicio)
    if fim:
        query = query.filter(models.Transacao.data_hora <= fim)
    transacoes = query.all()

    por_forma_pagamento: dict = {}
    for t in transacoes:
        por_forma_pagamento[t.forma_pagamento] = por_forma_pagamento.get(t.forma_pagamento, 0.0) + t.valor

    return schemas.RelatorioFinanceiroResponse(
        periodo_inicio=inicio,
        periodo_fim=fim or agora_utc(),
        total_arrecadado=sum(t.valor for t in transacoes),
        por_forma_pagamento=por_forma_pagamento,
        quantidade_transacoes=len(transacoes),
    )


@router.get(
    "/gestao/relatorio/cupons-duplicados",
    response_model=List[schemas.TentativaCupomDuplicadoOut],
    dependencies=[Depends(exigir_chave_gestao)],
)
def relatorio_cupons_duplicados(db: Session = Depends(get_db)):
    return db.query(models.TentativaCupomDuplicado).order_by(
        models.TentativaCupomDuplicado.data_hora.desc()
    ).all()
