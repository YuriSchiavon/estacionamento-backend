"""
Dois relatórios distintos (não confundir):

- Conciliação financeira: acha a diferença entre tickets impressos, pagos
  e liberados -- para bater com o extrato do banco/adquirente. Isento
  (dentro da tolerância) não é diferença, é o esperado; a diferença de
  verdade é ticket tarifado que saiu sem pagar.
- Dashboard: visão operacional geral (movimento no período, incluindo
  acessos de credenciado/mensalista) + pátio em tempo real (quantos
  veículos estão dentro agora, contagem "ao vivo", independente do
  filtro de período).

Ambos filtram por unidade (None = agrega todas -- "geral").
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .tempo import agora_utc


def _filtrar_unidade(query, coluna, unidade_id: Optional[int]):
    if unidade_id is not None:
        query = query.filter(coluna == unidade_id)
    return query


def montar_conciliacao(db: Session, inicio: Optional[datetime], fim: Optional[datetime], unidade_id: Optional[int]) -> dict:
    query_tickets = _filtrar_unidade(db.query(models.Ticket), models.Ticket.unidade_id, unidade_id)
    query_tickets = query_tickets.filter(models.Ticket.credenciado_id.is_(None))
    if inicio:
        query_tickets = query_tickets.filter(models.Ticket.data_hora_entrada >= inicio)
    if fim:
        query_tickets = query_tickets.filter(models.Ticket.data_hora_entrada <= fim)
    tickets = query_tickets.all()

    impressos = len(tickets)
    liberados = sum(1 for t in tickets if t.status == models.StatusTicket.finalizado)

    tarifados = [t for t in tickets if t.valor_calculado > 0]
    tarifados_pagos = [t for t in tarifados if t.transacoes]
    tarifados_sem_pagar = [
        t for t in tarifados if not t.transacoes and t.status == models.StatusTicket.finalizado
    ]
    valor_esperado = sum(t.valor_calculado for t in tarifados)

    query_transacoes = _filtrar_unidade(
        db.query(models.Transacao).join(models.Ticket), models.Ticket.unidade_id, unidade_id
    )
    if inicio:
        query_transacoes = query_transacoes.filter(models.Transacao.data_hora >= inicio)
    if fim:
        query_transacoes = query_transacoes.filter(models.Transacao.data_hora <= fim)
    transacoes = query_transacoes.all()

    por_forma_pagamento: dict = {}
    for tr in transacoes:
        por_forma_pagamento[tr.forma_pagamento] = por_forma_pagamento.get(tr.forma_pagamento, 0.0) + tr.valor
    valor_recebido = sum(tr.valor for tr in transacoes)

    query_mensalidades = _filtrar_unidade(
        db.query(models.PagamentoMensalidade).join(models.Credenciado),
        models.Credenciado.unidade_id, unidade_id,
    )
    if inicio:
        query_mensalidades = query_mensalidades.filter(models.PagamentoMensalidade.data_pagamento >= inicio)
    if fim:
        query_mensalidades = query_mensalidades.filter(models.PagamentoMensalidade.data_pagamento <= fim)
    valor_mensalidades = sum(m.valor for m in query_mensalidades.all())

    return dict(
        periodo_inicio=inicio,
        periodo_fim=fim or agora_utc(),
        tickets_impressos=impressos,
        tickets_liberados=liberados,
        tickets_tarifados=len(tarifados),
        tickets_tarifados_pagos=len(tarifados_pagos),
        tickets_tarifados_sem_pagar=len(tarifados_sem_pagar),
        valor_esperado=valor_esperado,
        valor_recebido=valor_recebido,
        diferenca_valor=round(valor_esperado - valor_recebido, 2),
        valor_mensalidades=valor_mensalidades,
        por_forma_pagamento=por_forma_pagamento,
    )


def montar_dashboard(db: Session, inicio: Optional[datetime], fim: Optional[datetime], unidade_id: Optional[int]) -> dict:
    query_entradas = _filtrar_unidade(db.query(models.Ticket), models.Ticket.unidade_id, unidade_id)
    query_entradas = query_entradas.filter(models.Ticket.credenciado_id.is_(None))
    if inicio:
        query_entradas = query_entradas.filter(models.Ticket.data_hora_entrada >= inicio)
    if fim:
        query_entradas = query_entradas.filter(models.Ticket.data_hora_entrada <= fim)
    entradas_no_periodo = query_entradas.count()

    # status == finalizado, não data_hora_saida.isnot(None): um ticket
    # tarifado pendente já tem data_hora_saida preenchida na verificação,
    # mas o carro só saiu de fato quando finaliza (liberar=True).
    query_saidas = _filtrar_unidade(db.query(models.Ticket), models.Ticket.unidade_id, unidade_id)
    query_saidas = query_saidas.filter(
        models.Ticket.credenciado_id.is_(None), models.Ticket.status == models.StatusTicket.finalizado
    )
    if inicio:
        query_saidas = query_saidas.filter(models.Ticket.data_hora_saida >= inicio)
    if fim:
        query_saidas = query_saidas.filter(models.Ticket.data_hora_saida <= fim)
    saidas_no_periodo = query_saidas.count()

    def _acessos_no_periodo(tipo: "models.TipoCredenciado") -> int:
        q = _filtrar_unidade(
            db.query(models.Ticket).join(models.Credenciado), models.Credenciado.unidade_id, unidade_id
        ).filter(models.Credenciado.tipo == tipo)
        if inicio:
            q = q.filter(models.Ticket.data_hora_entrada >= inicio)
        if fim:
            q = q.filter(models.Ticket.data_hora_entrada <= fim)
        return q.count()

    # Pátio "agora" -- sempre em tempo real, nunca filtrado por período.
    # Usa status != finalizado, não data_hora_saida: um ticket tarifado que
    # ainda não pagou já tem data_hora_saida preenchida (foi verificado na
    # cancela) mas o carro continua fisicamente parado, não passou.
    query_no_patio = _filtrar_unidade(db.query(models.Ticket), models.Ticket.unidade_id, unidade_id)
    query_no_patio = query_no_patio.filter(models.Ticket.status != models.StatusTicket.finalizado)
    veiculos_no_patio = query_no_patio.filter(models.Ticket.credenciado_id.is_(None)).count()

    def _no_patio_agora(tipo: "models.TipoCredenciado") -> int:
        q = _filtrar_unidade(
            db.query(models.Ticket).join(models.Credenciado), models.Credenciado.unidade_id, unidade_id
        ).filter(
            models.Ticket.status != models.StatusTicket.finalizado,
            models.Credenciado.tipo == tipo,
        )
        return q.count()

    query_transacoes = _filtrar_unidade(
        db.query(models.Transacao).join(models.Ticket), models.Ticket.unidade_id, unidade_id
    )
    if inicio:
        query_transacoes = query_transacoes.filter(models.Transacao.data_hora >= inicio)
    if fim:
        query_transacoes = query_transacoes.filter(models.Transacao.data_hora <= fim)
    por_forma_pagamento: dict = {}
    for tr in query_transacoes.all():
        por_forma_pagamento[tr.forma_pagamento] = por_forma_pagamento.get(tr.forma_pagamento, 0.0) + tr.valor

    return dict(
        periodo_inicio=inicio,
        periodo_fim=fim or agora_utc(),
        entradas_no_periodo=entradas_no_periodo,
        saidas_no_periodo=saidas_no_periodo,
        acessos_credenciado_no_periodo=_acessos_no_periodo(models.TipoCredenciado.credenciado),
        acessos_mensalista_no_periodo=_acessos_no_periodo(models.TipoCredenciado.mensalista),
        veiculos_no_patio_agora=veiculos_no_patio,
        veiculos_no_patio_credenciado=_no_patio_agora(models.TipoCredenciado.credenciado),
        veiculos_no_patio_mensalista=_no_patio_agora(models.TipoCredenciado.mensalista),
        por_forma_pagamento=por_forma_pagamento,
    )
