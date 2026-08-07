"""
Rotas de gestão (unidades, credenciados/mensalistas, estabelecimentos
conveniados, relatórios) e do fluxo de acesso por reconhecimento facial
nos totens de entrada/saída.

Autenticação: login por usuário/senha (ver app/auth.py e app/security.py).
Cada totem loga com uma conta presa a uma unidade e uma função
(entrada/validação/saída). No painel de gestão, "dono" enxerga/gerencia
todas as unidades (pode filtrar por uma específica ou ver "geral");
"gerente" fica sempre preso à própria unidade, mesmo que tente informar
outra -- nunca confiamos em unidade_id vindo do cliente quando o usuário
já está preso a uma.
"""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import credenciamento, models, schemas
from .auth import criar_usuario, gerar_senha_temporaria, slugify, username_disponivel
from .dashboard import montar_conciliacao, montar_dashboard
from .database import get_db
from .nfce import CNPJ_REGEX
from .security import (
    escopo_unidade,
    exigir_dono,
    exigir_gestao,
    exigir_liberacao_manual,
    exigir_operacao,
    exigir_totem_entrada,
    exigir_totem_saida,
)
from .tempo import agora_utc

router = APIRouter()


def _resolver_unidade_para_escrita(usuario: models.Usuario, unidade_id_payload: Optional[int]) -> int:
    """Toda criação de registro precisa saber a unidade. Gerente sempre usa
    a própria (ignora o que vier no payload); dono precisa informar
    explicitamente, já que gerencia várias."""
    if usuario.papel == models.PapelUsuario.dono:
        if not unidade_id_payload:
            raise HTTPException(422, "Informe a unidade_id (seu usuário gerencia mais de uma unidade)")
        return unidade_id_payload
    return usuario.unidade_id


def _verificar_acesso_unidade(usuario: models.Usuario, unidade_id_recurso: int):
    if usuario.papel != models.PapelUsuario.dono and unidade_id_recurso != usuario.unidade_id:
        raise HTTPException(404, "Recurso não encontrado")


# ---------------------------------------------------------------------
# UNIDADES -- cadastro só pra dono. Cada unidade nova já ganha as 3 contas
# de totem (entrada/validação/saída) prontas, pra reduzir setup manual.
# ---------------------------------------------------------------------
@router.post("/gestao/unidades", response_model=schemas.UnidadeCriadaResponse)
def criar_unidade(payload: schemas.UnidadeIn, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)):
    if usuario.papel != models.PapelUsuario.dono:
        raise HTTPException(403, "Só o dono pode cadastrar novas unidades")

    unidade = models.Unidade(
        nome=payload.nome,
        tolerancia_padrao_minutos=payload.tolerancia_padrao_minutos,
        valor_mensalidade=payload.valor_mensalidade,
        dias_validade_mensalidade=payload.dias_validade_mensalidade,
    )
    db.add(unidade)
    db.flush()

    slug = slugify(payload.nome)
    contas = []
    for papel, sufixo in (
        (models.PapelUsuario.totem_entrada, "entrada"),
        (models.PapelUsuario.totem_validacao, "validacao"),
        (models.PapelUsuario.totem_saida, "saida"),
    ):
        username = username_disponivel(db, f"{slug}-{sufixo}")
        senha = gerar_senha_temporaria()
        criar_usuario(db, username, senha, f"Totem {sufixo} - {payload.nome}", papel, unidade_id=unidade.id)
        contas.append(schemas.ContaCriada(username=username, senha=senha, papel=papel.value))

    db.commit()
    db.refresh(unidade)
    return schemas.UnidadeCriadaResponse(unidade=unidade, contas=contas)


@router.get("/gestao/unidades", response_model=List[schemas.UnidadeOut])
def listar_unidades(db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)):
    query = db.query(models.Unidade)
    if usuario.papel != models.PapelUsuario.dono:
        query = query.filter_by(id=usuario.unidade_id)
    return query.order_by(models.Unidade.nome).all()


@router.patch("/gestao/unidades/{unidade_id}", response_model=schemas.UnidadeOut)
def atualizar_unidade(
    unidade_id: int, payload: schemas.UnidadeUpdate, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    unidade = db.get(models.Unidade, unidade_id)
    if not unidade:
        raise HTTPException(404, "Unidade não encontrada")
    _verificar_acesso_unidade(usuario, unidade.id)

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(unidade, campo, valor)
    db.commit()
    db.refresh(unidade)
    return unidade


# ---------------------------------------------------------------------
# ACESSO POR RECONHECIMENTO FACIAL -- chamado pelos totens de entrada/saída
# ---------------------------------------------------------------------
@router.post("/credenciados/entrada", response_model=schemas.AcessoCredenciadoResponse)
def entrada_por_reconhecimento_facial(
    payload: schemas.IdentificacaoFacialRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_totem_entrada),
):
    credenciado = credenciamento.buscar_credenciado_ativo(db, payload.identificador_facial, usuario.unidade_id)
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
        unidade_id=usuario.unidade_id,
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


@router.post("/credenciados/saida", response_model=schemas.AcessoCredenciadoResponse)
def saida_por_reconhecimento_facial(
    payload: schemas.IdentificacaoFacialRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_totem_saida),
):
    credenciado = credenciamento.buscar_credenciado_ativo(db, payload.identificador_facial, usuario.unidade_id)
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
@router.post("/gestao/credenciados", response_model=schemas.CredenciadoOut)
def criar_credenciado(payload: schemas.CredenciadoIn, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)):
    unidade_id = _resolver_unidade_para_escrita(usuario, payload.unidade_id)

    existente = db.query(models.Credenciado).filter_by(
        unidade_id=unidade_id, identificador_facial=payload.identificador_facial
    ).first()
    if existente:
        raise HTTPException(409, "Já existe um credenciado com esse identificador facial nessa unidade")

    dados = payload.model_dump(exclude={"unidade_id"})
    credenciado = models.Credenciado(unidade_id=unidade_id, **dados)
    db.add(credenciado)
    db.commit()
    db.refresh(credenciado)
    return credenciado


@router.get("/gestao/credenciados", response_model=List[schemas.CredenciadoOut])
def listar_credenciados(
    unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.Credenciado)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    return query.order_by(models.Credenciado.nome).all()


@router.patch("/gestao/credenciados/{credenciado_id}", response_model=schemas.CredenciadoOut)
def atualizar_credenciado(
    credenciado_id: int, payload: schemas.CredenciadoUpdate, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    credenciado = db.get(models.Credenciado, credenciado_id)
    if not credenciado:
        raise HTTPException(404, "Credenciado não encontrado")
    _verificar_acesso_unidade(usuario, credenciado.unidade_id)

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(credenciado, campo, valor)

    db.commit()
    db.refresh(credenciado)
    return credenciado


@router.delete("/gestao/credenciados/{credenciado_id}")
def excluir_credenciado(
    credenciado_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_dono),
):
    """Exclusão de verdade (não é desativar) -- só o dono pode, e só se o
    credenciado nunca teve movimento real (nenhum acesso registrado, nenhum
    pagamento de mensalidade). Havendo histórico, usar PATCH ativo=false em
    vez de apagar -- não dá pra perder rastro de acesso/pagamento real."""
    credenciado = db.get(models.Credenciado, credenciado_id)
    if not credenciado:
        raise HTTPException(404, "Credenciado não encontrado")

    tem_tickets = db.query(models.Ticket).filter_by(credenciado_id=credenciado_id).first() is not None
    tem_pagamentos = db.query(models.PagamentoMensalidade).filter_by(credenciado_id=credenciado_id).first() is not None
    if tem_tickets or tem_pagamentos:
        raise HTTPException(
            409,
            "Não é possível excluir: há acessos ou pagamentos registrados para este credenciado. "
            "Desative em vez de excluir.",
        )

    db.delete(credenciado)
    db.commit()
    return {"detail": "Credenciado excluído"}


@router.post("/gestao/credenciados/{credenciado_id}/renovar", response_model=schemas.CredenciadoOut)
def renovar_mensalidade(
    credenciado_id: int, payload: schemas.RenovarMensalidadeRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    credenciado = db.get(models.Credenciado, credenciado_id)
    if not credenciado:
        raise HTTPException(404, "Credenciado não encontrado")
    _verificar_acesso_unidade(usuario, credenciado.unidade_id)
    if credenciado.tipo != models.TipoCredenciado.mensalista:
        raise HTTPException(409, "Renovação de mensalidade só se aplica a mensalistas")

    credenciamento.renovar_mensalidade(db, credenciado, payload.valor, payload.forma_pagamento)
    return credenciado


# ---------------------------------------------------------------------
# ESTABELECIMENTOS CONVENIADOS -- cada um com seu próprio regulamento de
# tolerância (contratos diferentes, regras diferentes), específico de uma
# unidade. O CNPJ é conferido contra o embutido na chave de acesso da
# NFC-e (ver app/nfce.py).
# ---------------------------------------------------------------------
@router.post("/gestao/estabelecimentos", response_model=schemas.EstabelecimentoOut)
def criar_estabelecimento(payload: schemas.EstabelecimentoIn, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)):
    if not CNPJ_REGEX.match(payload.cnpj):
        raise HTTPException(422, "CNPJ precisa ter 14 dígitos numéricos, sem pontuação")

    unidade_id = _resolver_unidade_para_escrita(usuario, payload.unidade_id)

    existente = db.query(models.Estabelecimento).filter_by(unidade_id=unidade_id, cnpj=payload.cnpj).first()
    if existente:
        raise HTTPException(409, "Já existe um estabelecimento com esse CNPJ nessa unidade")

    estabelecimento = models.Estabelecimento(unidade_id=unidade_id, cnpj=payload.cnpj, nome=payload.nome)
    db.add(estabelecimento)
    db.commit()
    db.refresh(estabelecimento)
    return estabelecimento


@router.get("/gestao/estabelecimentos", response_model=List[schemas.EstabelecimentoOut])
def listar_estabelecimentos(
    unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.Estabelecimento)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    return query.order_by(models.Estabelecimento.nome).all()


@router.patch("/gestao/estabelecimentos/{estabelecimento_id}", response_model=schemas.EstabelecimentoOut)
def atualizar_estabelecimento(
    estabelecimento_id: int, payload: schemas.EstabelecimentoUpdate, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    estabelecimento = db.get(models.Estabelecimento, estabelecimento_id)
    if not estabelecimento:
        raise HTTPException(404, "Estabelecimento não encontrado")
    _verificar_acesso_unidade(usuario, estabelecimento.unidade_id)

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(estabelecimento, campo, valor)

    db.commit()
    db.refresh(estabelecimento)
    return estabelecimento


@router.delete("/gestao/estabelecimentos/{estabelecimento_id}")
def excluir_estabelecimento(
    estabelecimento_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_dono),
):
    """Exclusão de verdade -- só o dono pode, e só se nenhum cupom fiscal já
    foi validado contra este estabelecimento. Havendo cupons, usar PATCH
    ativo=false em vez de apagar -- cupom fiscal é dado de auditoria real."""
    estabelecimento = db.get(models.Estabelecimento, estabelecimento_id)
    if not estabelecimento:
        raise HTTPException(404, "Estabelecimento não encontrado")

    tem_cupons = db.query(models.CupomFiscal).filter_by(estabelecimento_id=estabelecimento_id).first() is not None
    if tem_cupons:
        raise HTTPException(
            409,
            "Não é possível excluir: há cupons fiscais validados para este estabelecimento. "
            "Desative em vez de excluir.",
        )

    db.query(models.RegraTolerancia).filter_by(estabelecimento_id=estabelecimento_id).delete()
    db.delete(estabelecimento)
    db.commit()
    return {"detail": "Estabelecimento excluído"}


@router.post("/gestao/estabelecimentos/{estabelecimento_id}/regras-tolerancia", response_model=schemas.EstabelecimentoOut)
def adicionar_regra_tolerancia(
    estabelecimento_id: int, payload: schemas.RegraToleranciaIn, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    estabelecimento = db.get(models.Estabelecimento, estabelecimento_id)
    if not estabelecimento:
        raise HTTPException(404, "Estabelecimento não encontrado")
    _verificar_acesso_unidade(usuario, estabelecimento.unidade_id)

    existente = db.query(models.RegraTolerancia).filter_by(
        estabelecimento_id=estabelecimento_id, valor_minimo_compra=payload.valor_minimo_compra
    ).first()
    if existente:
        raise HTTPException(409, "Já existe uma regra com esse valor mínimo para este estabelecimento")

    regra = models.RegraTolerancia(
        estabelecimento_id=estabelecimento_id,
        valor_minimo_compra=payload.valor_minimo_compra,
        tolerancia_minutos=payload.tolerancia_minutos,
    )
    db.add(regra)
    db.commit()
    db.refresh(estabelecimento)
    return estabelecimento


@router.delete("/gestao/estabelecimentos/{estabelecimento_id}/regras-tolerancia/{regra_id}", response_model=schemas.EstabelecimentoOut)
def remover_regra_tolerancia(
    estabelecimento_id: int, regra_id: int, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    estabelecimento = db.get(models.Estabelecimento, estabelecimento_id)
    if not estabelecimento:
        raise HTTPException(404, "Estabelecimento não encontrado")
    _verificar_acesso_unidade(usuario, estabelecimento.unidade_id)

    regra = db.query(models.RegraTolerancia).filter_by(
        id=regra_id, estabelecimento_id=estabelecimento_id
    ).first()
    if not regra:
        raise HTTPException(404, "Regra não encontrada para este estabelecimento")

    db.delete(regra)
    db.commit()
    db.refresh(estabelecimento)
    return estabelecimento


# ---------------------------------------------------------------------
# RELATÓRIOS -- painel de gestão. unidade_id: None = "geral" (só funciona
# de verdade pra dono; gerente sempre vê só a própria, ver escopo_unidade).
# ---------------------------------------------------------------------
@router.get("/gestao/relatorio/tickets", response_model=List[schemas.TicketOut])
def relatorio_tickets(
    inicio: Optional[datetime] = None, fim: Optional[datetime] = None, unidade_id: Optional[int] = None,
    db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_operacao),
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.Ticket)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    if inicio:
        query = query.filter(models.Ticket.data_hora_entrada >= inicio)
    if fim:
        query = query.filter(models.Ticket.data_hora_entrada <= fim)
    return query.order_by(models.Ticket.data_hora_entrada.desc()).all()


@router.get("/gestao/relatorio/conciliacao", response_model=schemas.ConciliacaoResponse)
def relatorio_conciliacao(
    inicio: Optional[datetime] = None, fim: Optional[datetime] = None, unidade_id: Optional[int] = None,
    db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao),
):
    escopo = escopo_unidade(usuario, unidade_id)
    return montar_conciliacao(db, inicio, fim, escopo)


@router.get("/gestao/dashboard", response_model=schemas.DashboardResponse)
def dashboard(
    inicio: Optional[datetime] = None, fim: Optional[datetime] = None, unidade_id: Optional[int] = None,
    db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao),
):
    escopo = escopo_unidade(usuario, unidade_id)
    return montar_dashboard(db, inicio, fim, escopo)


@router.get("/gestao/relatorio/cupons-duplicados", response_model=List[schemas.TentativaCupomDuplicadoOut])
def relatorio_cupons_duplicados(
    unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.TentativaCupomDuplicado)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    return query.order_by(models.TentativaCupomDuplicado.data_hora.desc()).all()


# ---------------------------------------------------------------------
# LIBERAÇÃO MANUAL -- permissão elevada e própria (pode_liberar_manualmente),
# independente de ser dono/gerente. Não depende de um ticket válido existir
# (o ticket pode ser o problema).
# ---------------------------------------------------------------------
@router.post("/gestao/liberacao-manual", response_model=schemas.LiberacaoManualOut)
def liberar_manualmente(
    payload: schemas.LiberacaoManualRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_liberacao_manual),
):
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(422, "Motivo é obrigatório para liberação manual")

    ticket = None
    if payload.ticket_id is not None:
        ticket = db.get(models.Ticket, payload.ticket_id)
        if not ticket:
            raise HTTPException(404, "Ticket informado não encontrado")
        _verificar_acesso_unidade(usuario, ticket.unidade_id)
        unidade_id = ticket.unidade_id
        if ticket.status != models.StatusTicket.finalizado:
            if not ticket.data_hora_saida:
                ticket.data_hora_saida = agora_utc()
            ticket.status = models.StatusTicket.finalizado
    else:
        unidade_id = _resolver_unidade_para_escrita(usuario, payload.unidade_id)

    liberacao = models.LiberacaoManual(
        unidade_id=unidade_id,
        cancela=payload.cancela,
        motivo=motivo,
        ticket_id=ticket.id if ticket else None,
        usuario_nome=usuario.nome,
    )
    db.add(liberacao)
    db.commit()
    db.refresh(liberacao)
    return liberacao


@router.get("/gestao/relatorio/liberacoes-manuais", response_model=List[schemas.LiberacaoManualOut])
def relatorio_liberacoes_manuais(
    unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.LiberacaoManual)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    return query.order_by(models.LiberacaoManual.data_hora.desc()).all()


# ---------------------------------------------------------------------
# MANUTENÇÃO DO PÁTIO -- limpeza em massa (falha no fluxo automático) e
# exclusão de ticket avulso (erro de operação). Mesma permissão elevada da
# liberação manual individual.
# ---------------------------------------------------------------------
@router.post("/gestao/liberacao-manual/limpar-patio", response_model=List[schemas.LiberacaoManualOut])
def limpar_patio(
    payload: schemas.LimparPatioRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_liberacao_manual),
):
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(422, "Motivo é obrigatório para limpeza de pátio")

    # Nunca "geral", mesmo pra dono -- limpar todas as unidades de uma vez
    # por engano é exatamente o tipo de acidente que essa checagem evita.
    if usuario.papel == models.PapelUsuario.dono:
        if not payload.unidade_id:
            raise HTTPException(422, "Informe a unidade -- limpeza de pátio nunca vale para todas de uma vez")
        unidade_id = payload.unidade_id
    else:
        unidade_id = usuario.unidade_id

    tickets_abertos = db.query(models.Ticket).filter(
        models.Ticket.unidade_id == unidade_id,
        models.Ticket.status != models.StatusTicket.finalizado,
        models.Ticket.credenciado_id.is_(None),
    ).all()

    liberacoes = []
    for ticket in tickets_abertos:
        if not ticket.data_hora_saida:
            ticket.data_hora_saida = agora_utc()
        ticket.status = models.StatusTicket.finalizado

        liberacao = models.LiberacaoManual(
            unidade_id=unidade_id,
            cancela=None,
            via_limpeza_patio=True,
            motivo=f"Limpeza de pátio: {motivo}",
            ticket_id=ticket.id,
            usuario_nome=usuario.nome,
        )
        db.add(liberacao)
        liberacoes.append(liberacao)

    db.commit()
    for liberacao in liberacoes:
        db.refresh(liberacao)
    return liberacoes


@router.post("/gestao/tickets/{ticket_id}/excluir", response_model=schemas.ExclusaoTicketOut)
def excluir_ticket(
    ticket_id: int, payload: schemas.ExclusaoTicketRequest, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_liberacao_manual),
):
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(422, "Motivo é obrigatório para excluir um ticket")

    ticket = db.get(models.Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket não encontrado")
    _verificar_acesso_unidade(usuario, ticket.unidade_id)
    if ticket.transacoes:
        raise HTTPException(
            409,
            "Este ticket já tem pagamento registrado -- excluir corromperia a conciliação financeira",
        )
    if ticket.credenciado_id is not None:
        raise HTTPException(409, "Ticket de credenciado/mensalista não é excluído por aqui")

    exclusao = models.ExclusaoTicket(
        unidade_id=ticket.unidade_id, codigo_barras=ticket.codigo_barras, motivo=motivo, usuario_nome=usuario.nome,
    )
    db.add(exclusao)

    if ticket.cupom_fiscal:
        db.delete(ticket.cupom_fiscal)
    db.delete(ticket)
    db.commit()
    db.refresh(exclusao)
    return exclusao


@router.get("/gestao/relatorio/exclusoes-tickets", response_model=List[schemas.ExclusaoTicketOut])
def relatorio_exclusoes_tickets(
    unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.ExclusaoTicket)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    return query.order_by(models.ExclusaoTicket.data_hora.desc()).all()


# ---------------------------------------------------------------------
# AUDITORIA UNIFICADA -- junta liberação manual, exclusão de ticket e
# tentativa de cupom duplicado numa lista só, com filtro por tipo. Os
# endpoints individuais acima continuam existindo (nada mais depende só
# deles), mas o painel usa esta aqui como a aba principal de auditoria.
# ---------------------------------------------------------------------
@router.get("/gestao/relatorio/auditoria", response_model=List[schemas.AuditoriaEvento])
def relatorio_auditoria(
    tipo: Optional[Literal["liberacao_manual", "exclusao_ticket", "cupom_duplicado"]] = None,
    inicio: Optional[datetime] = None, fim: Optional[datetime] = None, unidade_id: Optional[int] = None,
    db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao),
):
    escopo = escopo_unidade(usuario, unidade_id)
    eventos: List[schemas.AuditoriaEvento] = []

    if tipo in (None, "liberacao_manual"):
        query = db.query(models.LiberacaoManual)
        if escopo is not None:
            query = query.filter_by(unidade_id=escopo)
        if inicio:
            query = query.filter(models.LiberacaoManual.data_hora >= inicio)
        if fim:
            query = query.filter(models.LiberacaoManual.data_hora <= fim)
        for liberacao in query.all():
            if liberacao.via_limpeza_patio:
                titulo = "Limpeza de pátio"
            elif liberacao.cancela:
                titulo = f"Liberação manual (cancela de {liberacao.cancela.value})"
            else:
                titulo = "Liberação manual"
            eventos.append(schemas.AuditoriaEvento(
                tipo="liberacao_manual",
                descricao=f"{titulo}: {liberacao.motivo}",
                unidade_id=liberacao.unidade_id,
                usuario_nome=liberacao.usuario_nome,
                data_hora=liberacao.data_hora,
                detalhes={
                    "ticket_id": liberacao.ticket_id,
                    "cancela": liberacao.cancela.value if liberacao.cancela else None,
                    "via_limpeza_patio": liberacao.via_limpeza_patio,
                },
            ))

    if tipo in (None, "exclusao_ticket"):
        query = db.query(models.ExclusaoTicket)
        if escopo is not None:
            query = query.filter_by(unidade_id=escopo)
        if inicio:
            query = query.filter(models.ExclusaoTicket.data_hora >= inicio)
        if fim:
            query = query.filter(models.ExclusaoTicket.data_hora <= fim)
        for exclusao in query.all():
            eventos.append(schemas.AuditoriaEvento(
                tipo="exclusao_ticket",
                descricao=f"Ticket {exclusao.codigo_barras} excluído: {exclusao.motivo}",
                unidade_id=exclusao.unidade_id,
                usuario_nome=exclusao.usuario_nome,
                data_hora=exclusao.data_hora,
                detalhes={"codigo_barras": exclusao.codigo_barras},
            ))

    if tipo in (None, "cupom_duplicado"):
        query = db.query(models.TentativaCupomDuplicado)
        if escopo is not None:
            query = query.filter_by(unidade_id=escopo)
        if inicio:
            query = query.filter(models.TentativaCupomDuplicado.data_hora >= inicio)
        if fim:
            query = query.filter(models.TentativaCupomDuplicado.data_hora <= fim)
        for tentativa in query.all():
            eventos.append(schemas.AuditoriaEvento(
                tipo="cupom_duplicado",
                descricao=f"Cupom já usado -- tentativa no ticket {tentativa.codigo_barras_tentativa}",
                unidade_id=tentativa.unidade_id,
                usuario_nome=None,
                data_hora=tentativa.data_hora,
                detalhes={
                    "chave_acesso_nfce": tentativa.chave_acesso_nfce,
                    "ticket_original_id": tentativa.ticket_original_id,
                },
            ))

    eventos.sort(key=lambda e: e.data_hora, reverse=True)
    return eventos


# ---------------------------------------------------------------------
# USUÁRIOS -- criação avulsa pelo painel (além da criação automática
# junto de uma unidade nova). Dono cria qualquer papel pra qualquer
# unidade (menos outro dono, que não tem unidade); gerente só cria
# operador pra própria unidade.
# ---------------------------------------------------------------------
@router.post("/gestao/usuarios", response_model=schemas.UsuarioCriadoResponse)
def criar_usuario_avulso(
    payload: schemas.UsuarioIn, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    papel = models.PapelUsuario(payload.papel)

    if usuario.papel == models.PapelUsuario.dono:
        if papel == models.PapelUsuario.dono:
            unidade_id = None
        else:
            if not payload.unidade_id:
                raise HTTPException(422, "Informe a unidade_id para esse papel")
            unidade_id = payload.unidade_id
    else:
        if papel != models.PapelUsuario.operador:
            raise HTTPException(403, "Seu usuário só pode criar contas de operador")
        unidade_id = usuario.unidade_id

    if papel == models.PapelUsuario.operador:
        cpf = (payload.cpf or "").strip()
        if not cpf.isdigit() or len(cpf) != 11:
            raise HTTPException(422, "Informe um CPF válido (11 dígitos, sem pontuação) para o operador")
        username_base = cpf
    else:
        username_base = slugify(payload.nome)

    username = username_disponivel(db, username_base)
    if payload.senha:
        if len(payload.senha) < 6:
            raise HTTPException(422, "A senha deve ter pelo menos 6 caracteres")
        senha = payload.senha
    else:
        senha = gerar_senha_temporaria()
    novo_usuario = criar_usuario(
        db, username, senha, payload.nome, papel,
        unidade_id=unidade_id, pode_liberar_manualmente=payload.pode_liberar_manualmente,
    )
    db.commit()
    db.refresh(novo_usuario)
    return schemas.UsuarioCriadoResponse(usuario=novo_usuario, senha=senha)


@router.get("/gestao/usuarios", response_model=List[schemas.UsuarioOut])
def listar_usuarios(
    unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_gestao)
):
    escopo = escopo_unidade(usuario, unidade_id)
    query = db.query(models.Usuario)
    if escopo is not None:
        query = query.filter_by(unidade_id=escopo)
    return query.order_by(models.Usuario.nome).all()


@router.patch("/gestao/usuarios/{usuario_id}", response_model=schemas.UsuarioOut)
def atualizar_usuario(
    usuario_id: int, payload: schemas.UsuarioUpdate, db: Session = Depends(get_db),
    usuario: models.Usuario = Depends(exigir_gestao),
):
    alvo = db.get(models.Usuario, usuario_id)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    if usuario.papel != models.PapelUsuario.dono:
        if alvo.unidade_id != usuario.unidade_id or alvo.papel != models.PapelUsuario.operador:
            raise HTTPException(404, "Usuário não encontrado")

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(alvo, campo, valor)
    db.commit()
    db.refresh(alvo)
    return alvo


@router.delete("/gestao/usuarios/{usuario_id}")
def excluir_usuario(
    usuario_id: int, db: Session = Depends(get_db), usuario: models.Usuario = Depends(exigir_dono),
):
    """Exclusão de verdade -- só o dono pode. Útil pra recriar uma conta do
    zero (ex: senha inicial perdida). Liberações manuais/exclusões de ticket
    já feitas por essa conta não são afetadas: guardam o nome como
    snapshot, não uma FK."""
    alvo = db.get(models.Usuario, usuario_id)
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado")
    if alvo.id == usuario.id:
        raise HTTPException(422, "Não é possível excluir a própria conta enquanto estiver logado nela")

    db.query(models.Sessao).filter_by(usuario_id=alvo.id).delete()
    db.delete(alvo)
    db.commit()
    return {"detail": "Usuário excluído"}
