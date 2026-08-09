"""
Regras de negócio de tolerância e tarifa.

- Sem cupom fiscal: tolerância padrão da própria unidade.
- Cupom de convênio do tipo "tolerância": minutos grátis por faixa de
  valor de compra (RegraTolerancia), configurado por convênio.
- Cupom de convênio do tipo "desconto_percentual": não dá minutos
  grátis -- em vez disso, aplica um desconto percentual sobre a tarifa
  calculada, mas só se a permanência tarifável couber dentro das horas
  fixas da regra (RegraDesconto); excedendo, cobra o valor cheio.
- É TOLERÂNCIA, não gratuidade: se ultrapassar o limite, cobra a
  permanência INTEIRA (não só o excedente).
- Tarifa (1ª hora, incremento por hora, teto da diária, granularidade
  hora cheia/fração de 15 min) é configurável por unidade -- ver
  Unidade em app/models.py -- não é mais uma constante global.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from . import models
from .tempo import agora_utc

# Ciclo da diária: 12h. Ao ultrapassar, a cobrança reinicia do zero para
# o novo ciclo, somando a diária anterior (ex.: 13h = 1 diária + a 1ª
# hora do novo ciclo).
CICLO_DIARIA_MINUTOS = 12 * 60


def calcular_tolerancia_minutos(
    db: Session,
    valor_compra: Optional[float],
    estabelecimento_id: Optional[int] = None,
    tolerancia_padrao_unidade: int = 15,
) -> int:
    """Retorna a maior tolerância aplicável.

    Sem cupom (valor_compra=None): usa a tolerância padrão da própria
    unidade (`Unidade.tolerancia_padrao_minutos`), a mesma pra qualquer
    entrada, independente de estabelecimento conveniado.

    Com cupom: usa só as regras do estabelecimento daquele cupom -- cada
    conveniado tem seu próprio contrato/regulamento, não compartilham
    tabela (ex: o regulamento do supermercado é diferente do de outra loja)."""
    if valor_compra is None:
        return tolerancia_padrao_unidade

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


def _melhor_desconto_elegivel(
    db: Session, estabelecimento_id: int, valor_compra: float, tempo_permanencia_minutos: int
) -> Optional["models.RegraDesconto"]:
    """Maior desconto elegível pro valor da compra, entre as regras cujas
    horas fixas ainda cobrem a permanência atual -- excedendo as horas
    fixas de uma regra, ela deixa de valer (cobra cheio, sem desconto)."""
    regras = db.query(models.RegraDesconto).filter_by(estabelecimento_id=estabelecimento_id).all()
    elegiveis = [
        r for r in regras
        if (r.valor_minimo_compra is None or valor_compra >= r.valor_minimo_compra)
        and tempo_permanencia_minutos <= r.horas_fixas * 60
    ]
    if not elegiveis:
        return None
    return max(elegiveis, key=lambda r: r.percentual_desconto)


def calcular_tarifa(
    tempo_permanencia_minutos: int,
    valor_primeira_hora: float,
    incremento_por_hora: float,
    valor_diaria: float,
    granularidade: str,
) -> float:
    """Qualquer fração de hora (ou de 15 min, se a granularidade for
    fracao_15min) iniciada já cobra a unidade de cobrança seguinte. O
    teto da diária é sempre um limite (nunca cobra mais que
    valor_diaria por ciclo de 12h), não depende de uma contagem de
    horas separada -- assim nunca descasa dos valores configurados."""
    diarias_completas, minutos_no_ciclo = divmod(tempo_permanencia_minutos, CICLO_DIARIA_MINUTOS)
    valor = diarias_completas * valor_diaria

    if minutos_no_ciclo > 0:
        if granularidade == models.GranularidadeCobranca.fracao_15min.value:
            minutos_por_unidade, unidades_por_hora = 15, 4
        else:
            minutos_por_unidade, unidades_por_hora = 60, 1
        unidades = -(-minutos_no_ciclo // minutos_por_unidade)  # arredonda pra cima
        # As primeiras `unidades_por_hora` unidades (a 1ª hora inteira,
        # em blocos) somam exatamente valor_primeira_hora no total; cada
        # unidade além dessas soma incremento_por_hora/unidades_por_hora
        # -- assim uma permanência de 60 min sempre dá o mesmo valor,
        # seja qual for a granularidade configurada.
        valor_ciclo = (
            valor_primeira_hora / unidades_por_hora * min(unidades, unidades_por_hora)
            + incremento_por_hora / unidades_por_hora * max(0, unidades - unidades_por_hora)
        )
        valor += min(valor_ciclo, valor_diaria)

    return round(valor, 2)


def processar_saida(db: Session, ticket: models.Ticket, agora: datetime = None):
    """Calcula permanência, aplica tolerância/desconto (considerando
    cupom já vinculado, se houver) e define se a cancela deve abrir."""
    agora = agora or agora_utc()

    # Pré-pago na entrada (se a unidade permite) -- libera direto,
    # nunca recalcula tolerância/tarifa.
    if ticket.pre_pago:
        ticket.data_hora_saida = agora
        ticket.tempo_permanencia_minutos = int((agora - ticket.data_hora_entrada).total_seconds() // 60)
        ticket.tolerancia_aplicada_minutos = 0  # não se aplica -- já foi pago fixo na entrada
        ticket.status = models.StatusTicket.finalizado
        db.commit()
        db.refresh(ticket)
        return True, "Pré-pago na entrada"

    tempo_permanencia = int((agora - ticket.data_hora_entrada).total_seconds() // 60)

    cupom = ticket.cupom_fiscal
    estabelecimento = cupom.estabelecimento if cupom else None
    eh_convenio_desconto = (
        estabelecimento is not None
        and estabelecimento.tipo_beneficio == models.TipoBeneficioConvenio.desconto_percentual
    )

    # Convênio de desconto não dá minutos grátis -- só desconto na
    # tarifa (calculado mais abaixo, se ultrapassar a tolerância). Pro
    # cálculo de tolerância, é como se não tivesse cupom nenhum vinculado.
    valor_compra_tolerancia = cupom.valor_compra if (cupom and not eh_convenio_desconto) else None
    estabelecimento_id_tolerancia = cupom.estabelecimento_id if (cupom and not eh_convenio_desconto) else None
    tolerancia = calcular_tolerancia_minutos(
        db, valor_compra_tolerancia, estabelecimento_id_tolerancia, ticket.unidade.tolerancia_padrao_minutos
    )

    ticket.data_hora_saida = agora
    ticket.tempo_permanencia_minutos = tempo_permanencia
    ticket.tolerancia_aplicada_minutos = tolerancia

    if tempo_permanencia <= tolerancia:
        ticket.status = models.StatusTicket.isento
        ticket.valor_calculado = 0.0
        liberar = True
        motivo = f"Dentro da tolerância ({tolerancia} min)"
    else:
        unidade = ticket.unidade
        valor = calcular_tarifa(
            tempo_permanencia, unidade.valor_primeira_hora, unidade.incremento_por_hora,
            unidade.valor_diaria, unidade.granularidade_cobranca,
        )

        desconto = None
        if eh_convenio_desconto:
            desconto = _melhor_desconto_elegivel(db, estabelecimento.id, cupom.valor_compra, tempo_permanencia)
            if desconto:
                valor = round(valor * (1 - desconto.percentual_desconto / 100), 2)

        ticket.valor_calculado = valor
        if ticket.status == models.StatusTicket.pago:
            liberar = True
            motivo = "Pagamento já confirmado"
        else:
            ticket.status = models.StatusTicket.tarifado
            liberar = False
            motivo = f"Excedeu tolerância ({tolerancia} min) — valor a pagar: R$ {valor:.2f}"
            if desconto:
                motivo = (
                    f"Excedeu tolerância ({tolerancia} min) -- {desconto.percentual_desconto:.0f}% de "
                    f"desconto do convênio aplicado -- valor a pagar: R$ {valor:.2f}"
                )

    if liberar:
        ticket.status = models.StatusTicket.finalizado

    db.commit()
    db.refresh(ticket)
    return liberar, motivo
