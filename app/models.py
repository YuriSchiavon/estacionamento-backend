"""
Modelo de dados do sistema de controle de acesso do estacionamento.

Tabelas:
- Ticket: um registro por veículo, criado na entrada e fechado na saída.
- CupomFiscal: nota fiscal (NFC-e) validada no totem de autoatendimento,
  vinculada a um único ticket (chave de acesso é UNIQUE para impedir reuso).
- RegraTolerancia: tabela de faixas de tolerância por valor de compra.
  valor_minimo_compra = None representa a tolerância padrão (sem cupom).
- Transacao: pagamentos efetuados (quando a permanência ultrapassa a tolerância).
- Credenciado: pessoa reconhecida por identificador facial no totem, com
  acesso liberado sem passar pelo fluxo normal de ticket/tolerância/cupom.
  Dois tipos: credenciado (sempre liberado) e mensalista (liberado enquanto
  a mensalidade estiver em dia -- ver PagamentoMensalidade).
- PagamentoMensalidade: histórico de renovações de mensalistas.
- TentativaCupomDuplicado: auditoria de tentativas de reuso de cupom fiscal.
"""
import uuid

from sqlalchemy import (
    Column, String, DateTime, Float, Integer, ForeignKey, Enum, Boolean
)
from sqlalchemy.orm import relationship
import enum

from .database import Base
from .tempo import agora_utc


def gerar_codigo_barras() -> str:
    return uuid.uuid4().hex[:16].upper()


class StatusTicket(str, enum.Enum):
    aberto = "aberto"        # veículo entrou, ainda não saiu
    isento = "isento"        # dentro da tolerância, sem cobrança
    tarifado = "tarifado"    # excedeu a tolerância, valor calculado
    pago = "pago"            # valor tarifado foi pago
    finalizado = "finalizado"  # veículo já saiu (cancela liberada)


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    codigo_barras = Column(String, unique=True, index=True, default=gerar_codigo_barras)

    data_hora_entrada = Column(DateTime, default=agora_utc)
    data_hora_saida = Column(DateTime, nullable=True)

    gate_entrada = Column(String, default="entrada-1")
    gate_saida = Column(String, nullable=True)

    status = Column(Enum(StatusTicket), default=StatusTicket.aberto)

    tempo_permanencia_minutos = Column(Integer, nullable=True)
    tolerancia_aplicada_minutos = Column(Integer, nullable=True)
    valor_calculado = Column(Float, default=0.0)

    # Preenchido só quando a entrada/saída aconteceu por reconhecimento
    # facial (credenciado/mensalista) em vez do fluxo normal de ticket.
    credenciado_id = Column(Integer, ForeignKey("credenciados.id"), nullable=True)

    cupom_fiscal = relationship("CupomFiscal", back_populates="ticket", uselist=False)
    transacoes = relationship("Transacao", back_populates="ticket")
    credenciado = relationship("Credenciado", back_populates="tickets")


class CupomFiscal(Base):
    __tablename__ = "cupons_fiscais"

    id = Column(Integer, primary_key=True)
    chave_acesso_nfce = Column(String(44), unique=True, index=True, nullable=False)
    cnpj_estabelecimento = Column(String, nullable=True)
    valor_compra = Column(Float, nullable=False)
    data_hora_emissao = Column(DateTime, nullable=True)
    data_hora_validacao = Column(DateTime, default=agora_utc)

    ticket_id = Column(Integer, ForeignKey("tickets.id"), unique=True)
    ticket = relationship("Ticket", back_populates="cupom_fiscal")


class RegraTolerancia(Base):
    __tablename__ = "regras_tolerancia"

    id = Column(Integer, primary_key=True)
    # None = regra padrão, aplicada quando não há cupom fiscal validado
    valor_minimo_compra = Column(Float, nullable=True, unique=True)
    tolerancia_minutos = Column(Integer, nullable=False)


class Transacao(Base):
    __tablename__ = "transacoes"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    forma_pagamento = Column(String)  # pix | cartao | dinheiro
    valor = Column(Float)
    data_hora = Column(DateTime, default=agora_utc)

    ticket = relationship("Ticket", back_populates="transacoes")


class TipoCredenciado(str, enum.Enum):
    credenciado = "credenciado"  # acesso 100% liberado, sem custo, sem validade
    mensalista = "mensalista"    # acesso liberado enquanto a mensalidade estiver em dia


class Credenciado(Base):
    __tablename__ = "credenciados"

    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    documento = Column(String, nullable=True)
    placa = Column(String, nullable=True)
    empresa_vinculo = Column(String, nullable=True)
    tipo = Column(Enum(TipoCredenciado), nullable=False)

    # Retornado pelo SDK de reconhecimento facial do totem -- identifica a
    # pessoa sem precisar de ticket/cupom físico.
    identificador_facial = Column(String, unique=True, index=True, nullable=False)

    ativo = Column(Boolean, default=True)
    # Só se aplica a mensalistas; None = nunca pagou / sem mensalidade ativa.
    data_validade = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, default=agora_utc)

    tickets = relationship("Ticket", back_populates="credenciado")
    pagamentos = relationship("PagamentoMensalidade", back_populates="credenciado")


class PagamentoMensalidade(Base):
    __tablename__ = "pagamentos_mensalidade"

    id = Column(Integer, primary_key=True)
    credenciado_id = Column(Integer, ForeignKey("credenciados.id"), nullable=False)
    valor = Column(Float, nullable=False)
    forma_pagamento = Column(String, default="pix")
    dias_adicionados = Column(Integer, nullable=False)
    validade_anterior = Column(DateTime, nullable=True)
    nova_validade = Column(DateTime, nullable=False)
    data_pagamento = Column(DateTime, default=agora_utc)

    credenciado = relationship("Credenciado", back_populates="pagamentos")


class TentativaCupomDuplicado(Base):
    """Auditoria: registrada toda vez que alguém tenta validar um cupom
    fiscal cuja chave de acesso já foi usada em outro ticket."""
    __tablename__ = "tentativas_cupom_duplicado"

    id = Column(Integer, primary_key=True)
    chave_acesso_nfce = Column(String(44), nullable=False)
    codigo_barras_tentativa = Column(String, nullable=False)
    ticket_original_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    data_hora = Column(DateTime, default=agora_utc)
