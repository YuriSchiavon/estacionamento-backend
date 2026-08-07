"""
Regras de negócio combinadas nas últimas conversas:

- Sem cupom fiscal: tolerância padrão de 15 minutos.
- Cupom de qualquer valor: tolerância de 30 minutos.
- Cupom >= R$ 45,00: tolerância de 60 minutos.
- Cupom >= R$ 90,00: tolerância de 90 minutos.
- Cupom >= R$ 150,00: tolerância de 360 minutos (6h).
- É TOLERÂNCIA, não gratuidade: se ultrapassar o limite, cobra a
  permanência INTEIRA (não só o excedente).
"""
from datetime import datetime
from sqlalchemy.orm import Session

from . import models
from .tempo import agora_utc

# Tabela de tarifa real (MY PARK):
# 1ª hora R$10, cada hora adicional +R$5, até travar em R$35 (diária de 12h).
# Qualquer fração de hora iniciada já cobra a hora cheia seguinte.
# Ao ultrapassar as 12h, a cobrança reinicia do zero para o novo ciclo,
# somando a diária anterior (ex.: 13h = 1 diária de R$35 + R$10 da 1ª hora
# do novo ciclo).
VALOR_PRIMEIRA_HORA = 10.0
INCREMENTO_POR_HORA = 5.0
VALOR_DIARIA = 35.0
CICLO_DIARIA_MINUTOS = 12 * 60
HORAS_ATE_TRAVAR_NA_DIARIA = 6  # 10 + 5*(6-1) = 35 = VALOR_DIARIA


def calcular_tolerancia_minutos(
    db: Session, valor_compra: float | None, estabelecimento_id: int | None = None
) -> int:
    """Retorna a maior tolerância aplicável.

    Sem cupom (valor_compra=None): usa a regra padrão global, a mesma pra
    qualquer entrada, independente de estabelecimento conveniado.

    Com cupom: usa só as regras do estabelecimento daquele cupom -- cada
    conveniado tem seu próprio contrato/regulamento, não compartilham
    tabela (ex: o regulamento do supermercado é diferente do de outra loja)."""
    if valor_compra is None:
        padrao = db.query(models.RegraTolerancia).filter_by(
            estabelecimento_id=None, valor_minimo_compra=None
        ).first()
        return padrao.tolerancia_minutos if padrao else 15

    regras = db.query(models.RegraTolerancia).filter_by(
        estabelecimento_id=estabelecimento_id
    ).all()

    elegiveis = [
        r for r in regras
        if r.valor_minimo_compra is not None and valor_compra >= r.valor_minimo_compra
    ]
    if not elegiveis:
        # cupom existe mas não bate nenhuma faixa com valor mínimo -> ainda
        # assim tem direito à tolerância "qualquer valor de cupom" (0.01)
        base = next((r for r in regras if r.valor_minimo_compra == 0.01), None)
        return base.tolerancia_minutos if base else 30

    return max(r.tolerancia_minutos for r in elegiveis)


def calcular_tarifa(tempo_permanencia_minutos: int) -> float:
    diarias_completas, minutos_no_ciclo = divmod(tempo_permanencia_minutos, CICLO_DIARIA_MINUTOS)
    valor = diarias_completas * VALOR_DIARIA

    if minutos_no_ciclo > 0:
        horas = -(-minutos_no_ciclo // 60)  # arredonda pra cima: fração inicia a próxima hora
        horas = min(horas, HORAS_ATE_TRAVAR_NA_DIARIA)
        valor += VALOR_PRIMEIRA_HORA + INCREMENTO_POR_HORA * (horas - 1)

    return round(valor, 2)


def processar_saida(db: Session, ticket: models.Ticket, agora: datetime | None = None):
    """Calcula permanência, aplica tolerância (considerando cupom já
    vinculado, se houver) e define se a cancela deve abrir."""
    agora = agora or agora_utc()
    tempo_permanencia = int((agora - ticket.data_hora_entrada).total_seconds() // 60)

    valor_compra = ticket.cupom_fiscal.valor_compra if ticket.cupom_fiscal else None
    estabelecimento_id = ticket.cupom_fiscal.estabelecimento_id if ticket.cupom_fiscal else None
    tolerancia = calcular_tolerancia_minutos(db, valor_compra, estabelecimento_id)

    ticket.data_hora_saida = agora
    ticket.tempo_permanencia_minutos = tempo_permanencia
    ticket.tolerancia_aplicada_minutos = tolerancia

    if tempo_permanencia <= tolerancia:
        ticket.status = models.StatusTicket.isento
        ticket.valor_calculado = 0.0
        liberar = True
        motivo = f"Dentro da tolerância ({tolerancia} min)"
    else:
        valor = calcular_tarifa(tempo_permanencia)
        ticket.valor_calculado = valor
        if ticket.status == models.StatusTicket.pago:
            liberar = True
            motivo = "Pagamento já confirmado"
        else:
            ticket.status = models.StatusTicket.tarifado
            liberar = False
            motivo = f"Excedeu tolerância ({tolerancia} min) — valor a pagar: R$ {valor:.2f}"

    if liberar:
        ticket.status = models.StatusTicket.finalizado

    db.commit()
    db.refresh(ticket)
    return liberar, motivo
