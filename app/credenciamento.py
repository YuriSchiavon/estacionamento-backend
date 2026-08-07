"""
Regras de acesso para credenciados e mensalistas, reconhecidos por
identificador facial (retornado pelo SDK de reconhecimento facial do totem
de entrada/saída, em vez do fluxo normal de ticket/cupom/tolerância).

- Credenciado: acesso 100% liberado, sem custo, sem validade.
- Mensalista: acesso liberado enquanto a mensalidade estiver em dia.
  Valor e dias de validade são configurados por unidade (`Unidade.
  valor_mensalidade` / `dias_validade_mensalidade`, ver app/models.py) --
  contratos diferentes, preços diferentes. Renovar antes de vencer soma os
  dias à validade atual (não perde dias pagos antecipadamente); renovar
  depois de vencido conta os dias a partir da data do pagamento.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import models
from .tempo import agora_utc


def buscar_credenciado_ativo(db: Session, identificador_facial: str, unidade_id: int) -> Optional[models.Credenciado]:
    return db.query(models.Credenciado).filter_by(
        identificador_facial=identificador_facial, unidade_id=unidade_id, ativo=True
    ).first()


def acesso_liberado(credenciado: models.Credenciado, agora: Optional[datetime] = None) -> tuple[bool, str]:
    agora = agora or agora_utc()

    if credenciado.tipo == models.TipoCredenciado.credenciado:
        return True, "Credenciado -- acesso liberado"

    if credenciado.data_validade and credenciado.data_validade >= agora:
        return True, f"Mensalista em dia (válido até {credenciado.data_validade.strftime('%d/%m/%Y')})"

    return False, "Mensalidade vencida -- necessário renovar"


def renovar_mensalidade(
    db: Session,
    credenciado: models.Credenciado,
    valor: Optional[float],
    forma_pagamento: str,
    agora: Optional[datetime] = None,
) -> models.PagamentoMensalidade:
    agora = agora or agora_utc()
    unidade = credenciado.unidade
    valor = valor if valor is not None else unidade.valor_mensalidade
    dias = unidade.dias_validade_mensalidade

    validade_anterior = credenciado.data_validade

    # Se ainda está em dia, soma os dias à validade atual (não perde dias
    # pagos antecipadamente); se venceu ou nunca pagou, conta a partir de hoje.
    base = validade_anterior if (validade_anterior and validade_anterior >= agora) else agora
    nova_validade = base + timedelta(days=dias)

    pagamento = models.PagamentoMensalidade(
        credenciado_id=credenciado.id,
        valor=valor,
        forma_pagamento=forma_pagamento,
        dias_adicionados=dias,
        validade_anterior=validade_anterior,
        nova_validade=nova_validade,
        data_pagamento=agora,
    )
    credenciado.data_validade = nova_validade

    db.add(pagamento)
    db.commit()
    db.refresh(credenciado)
    return pagamento
