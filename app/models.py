"""
Modelo de dados do sistema de controle de acesso do estacionamento.

Multi-unidade: o sistema atende várias unidades (estacionamentos)
independentes -- cada uma com seus próprios tickets, credenciados,
estabelecimentos conveniados e usuários/totens. Praticamente toda tabela
carrega `unidade_id` (direto ou indiretamente).

Tabelas:
- Unidade: um estacionamento/local. Tem seu próprio padrão de tolerância
  "sem cupom" (`tolerancia_padrao_minutos`).
- Usuario: login de pessoas (dono, gerente de operações, supervisor) e de
  totens (um por função).
  `dono` enxerga todas as unidades; os demais papéis pertencem a uma só.
- Sessao: token de login ativo (opaco, revogável na hora apagando a linha).
- Ticket: um registro por veículo, criado na entrada e fechado na saída.
- Estabelecimento: um conveniado (ex: um contrato de supermercado, uma loja
  de shopping) de uma unidade específica, identificado pelo CNPJ. Cada um
  tem seu próprio conjunto de regras de tolerância -- contratos diferentes,
  regulamentos diferentes, mesmo que seja o "mesmo" CNPJ em outra unidade.
- CupomFiscal: nota fiscal (NFC-e) validada no totem de autoatendimento,
  vinculada a um único ticket (chave de acesso é UNIQUE para impedir reuso)
  e a um Estabelecimento conveniado (identificado pelo CNPJ embutido na
  própria chave de acesso -- não dá pra falsificar sem invalidar a chave).
- RegraTolerancia: faixas de tolerância por valor de compra, por
  estabelecimento.
- Transacao: pagamentos efetuados (quando a permanência ultrapassa a tolerância).
- Credenciado: pessoa reconhecida por identificador facial no totem, com
  acesso liberado sem passar pelo fluxo normal de ticket/tolerância/cupom.
  Dois tipos: credenciado (sempre liberado) e mensalista (liberado enquanto
  a mensalidade estiver em dia -- ver PagamentoMensalidade).
- PagamentoMensalidade: histórico de renovações de mensalistas.
- TentativaCupomDuplicado: auditoria de tentativas de reuso de cupom fiscal.
- LiberacaoManual: auditoria de liberação de cancela feita pelo painel.
- ExclusaoTicket: auditoria de exclusão de ticket avulso.
"""
import enum
import uuid

from sqlalchemy import (
    Column, String, DateTime, Float, Integer, ForeignKey, Enum, Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base
from .tempo import agora_utc


class Unidade(Base):
    __tablename__ = "unidades"

    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    ativo = Column(Boolean, default=True)
    # Tolerância "sem cupom", aplicada a qualquer entrada dessa unidade que
    # não vincule nenhum cupom fiscal conveniado.
    tolerancia_padrao_minutos = Column(Integer, nullable=False, default=15)
    # Preço da mensalidade -- cada unidade define o próprio (contratos
    # diferentes). Ver app/credenciamento.py.
    valor_mensalidade = Column(Float, nullable=False, default=200.0)
    dias_validade_mensalidade = Column(Integer, nullable=False, default=30)
    criado_em = Column(DateTime, default=agora_utc)


class PapelUsuario(str, enum.Enum):
    dono = "dono"                                    # vê/gerencia todas as unidades
    gerente_operacoes = "gerente_operacoes"          # mesmas permissões do dono (multi-unidade) -- cargo separado, mesmo nível de acesso
    supervisor = "supervisor"                        # vê/gerencia uma unidade específica (antigo "gerente")
    operador = "operador"                            # opera o dia a dia de uma unidade (estacionamento assistido)
    totem_entrada = "totem_entrada"
    totem_validacao = "totem_validacao"
    totem_saida = "totem_saida"


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    nome = Column(String, nullable=False)
    papel = Column(Enum(PapelUsuario), nullable=False)

    # Obrigatório pra todo papel exceto "dono"/"gerente_operacoes" (que
    # enxergam todas as unidades).
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=True)

    # Permissão elevada e independente do papel -- só quem tem essa flag
    # consegue liberar cancela manualmente ou limpar o pátio, mesmo sendo
    # dono/gerente de operações/supervisor. Ver app/security.py exigir_liberacao_manual.
    pode_liberar_manualmente = Column(Boolean, default=False)

    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=agora_utc)

    unidade = relationship("Unidade")


class UnidadeAutorizada(Base):
    """Unidades extras que um operador pode escolher operar, além da
    `unidade_id` principal em Usuario. Só operador usa isso na prática --
    dono/gerente_operacoes já enxergam todas via PAPEIS_NIVEL_DONO, e
    supervisor/totem_* ficam presos à própria unidade."""
    __tablename__ = "unidades_autorizadas"
    __table_args__ = (
        UniqueConstraint("usuario_id", "unidade_id", name="uq_usuario_unidade_autorizada"),
    )

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)

    usuario = relationship("Usuario", backref="unidades_autorizadas")
    unidade = relationship("Unidade")


class Sessao(Base):
    """Token de login opaco -- revogável na hora (basta apagar a linha),
    diferente de um JWT auto-contido que continuaria válido até expirar."""
    __tablename__ = "sessoes"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    criado_em = Column(DateTime, default=agora_utc)
    expira_em = Column(DateTime, nullable=False)

    usuario = relationship("Usuario")


class Estabelecimento(Base):
    __tablename__ = "estabelecimentos"
    __table_args__ = (
        UniqueConstraint("unidade_id", "cnpj", name="uq_estabelecimento_por_unidade"),
    )

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    cnpj = Column(String(14), index=True, nullable=False)
    nome = Column(String, nullable=False)
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=agora_utc)

    unidade = relationship("Unidade")
    regras_tolerancia = relationship("RegraTolerancia", back_populates="estabelecimento")
    cupons = relationship("CupomFiscal", back_populates="estabelecimento")


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
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
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

    unidade = relationship("Unidade")
    cupom_fiscal = relationship("CupomFiscal", back_populates="ticket", uselist=False)
    transacoes = relationship("Transacao", back_populates="ticket")
    credenciado = relationship("Credenciado", back_populates="tickets")


class CupomFiscal(Base):
    __tablename__ = "cupons_fiscais"

    id = Column(Integer, primary_key=True)
    chave_acesso_nfce = Column(String(44), unique=True, index=True, nullable=False)
    # Derivado da própria chave de acesso na validação -- não é um dado
    # declarado pelo totem, então não dá pra informar um CNPJ falso.
    cnpj_estabelecimento = Column(String(14), nullable=False)
    estabelecimento_id = Column(Integer, ForeignKey("estabelecimentos.id"), nullable=False)
    valor_compra = Column(Float, nullable=False)
    data_hora_emissao = Column(DateTime, nullable=True)
    data_hora_validacao = Column(DateTime, default=agora_utc)

    ticket_id = Column(Integer, ForeignKey("tickets.id"), unique=True)
    ticket = relationship("Ticket", back_populates="cupom_fiscal")
    estabelecimento = relationship("Estabelecimento", back_populates="cupons")


class RegraTolerancia(Base):
    __tablename__ = "regras_tolerancia"
    __table_args__ = (
        UniqueConstraint("estabelecimento_id", "valor_minimo_compra", name="uq_regra_por_estabelecimento"),
    )

    id = Column(Integer, primary_key=True)
    estabelecimento_id = Column(Integer, ForeignKey("estabelecimentos.id"), nullable=False)
    # None = "qualquer valor de compra desse estabelecimento".
    valor_minimo_compra = Column(Float, nullable=True)
    tolerancia_minutos = Column(Integer, nullable=False)

    estabelecimento = relationship("Estabelecimento", back_populates="regras_tolerancia")


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
    __table_args__ = (
        UniqueConstraint("unidade_id", "identificador_facial", name="uq_credenciado_por_unidade"),
    )

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    nome = Column(String, nullable=False)
    documento = Column(String, nullable=True)
    placa = Column(String, nullable=True)
    empresa_vinculo = Column(String, nullable=True)
    tipo = Column(Enum(TipoCredenciado), nullable=False)

    # Retornado pelo SDK de reconhecimento facial do totem -- identifica a
    # pessoa sem precisar de ticket/cupom físico.
    identificador_facial = Column(String, index=True, nullable=False)

    ativo = Column(Boolean, default=True)
    # Só se aplica a mensalistas; None = nunca pagou / sem mensalidade ativa.
    data_validade = Column(DateTime, nullable=True)
    criado_em = Column(DateTime, default=agora_utc)

    unidade = relationship("Unidade")
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
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    chave_acesso_nfce = Column(String(44), nullable=False)
    codigo_barras_tentativa = Column(String, nullable=False)
    ticket_original_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    data_hora = Column(DateTime, default=agora_utc)


class Cancela(str, enum.Enum):
    entrada = "entrada"
    saida = "saida"


class LiberacaoManual(Base):
    """Auditoria: toda liberação de cancela feita manualmente pelo painel de
    gestão (em vez do fluxo automático) fica registrada aqui -- qual cancela,
    quem fez, motivo obrigatório e quando aconteceu.

    ticket_id é opcional de propósito: a liberação manual existe justamente
    para os casos em que o ticket falhou ou nem chegou a existir (ex: totem
    travou, impressora falhou) -- não pode depender de um ticket válido.

    cancela é opcional porque a limpeza de pátio em massa (via_limpeza_patio)
    não abre cancela nenhuma, só finaliza tickets presos -- não faz sentido
    apontar uma cancela nesse caso."""
    __tablename__ = "liberacoes_manuais"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    cancela = Column(Enum(Cancela), nullable=True)
    motivo = Column(String, nullable=False)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=True)
    via_limpeza_patio = Column(Boolean, default=False)
    # Snapshot do nome de quem executou -- não é FK de propósito, pra
    # sobreviver mesmo se a conta for desativada/excluída depois (mesmo
    # padrão do codigo_barras em ExclusaoTicket, abaixo).
    usuario_nome = Column(String, nullable=False)
    data_hora = Column(DateTime, default=agora_utc)

    ticket = relationship("Ticket")


class ExclusaoTicket(Base):
    """Auditoria de exclusão de ticket avulso (ex: duplicado por engano,
    ticket de teste). Guarda o código de barras como texto porque o ticket
    em si é removido -- não dá pra manter uma FK para uma linha apagada."""
    __tablename__ = "exclusoes_ticket"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    codigo_barras = Column(String, nullable=False)
    motivo = Column(String, nullable=False)
    usuario_nome = Column(String, nullable=False)
    data_hora = Column(DateTime, default=agora_utc)
