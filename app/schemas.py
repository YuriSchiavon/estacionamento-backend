from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, model_validator


class ComDatasUTC(BaseModel):
    """Datas no banco são salvas sem timezone (naive UTC -- ver
    app/tempo.py). Sem marcar isso explicitamente antes de serializar, o
    navegador interpreta a string ISO como horário local em vez de UTC, e
    o horário mostrado sai errado (adiantado, já que o Brasil está atrás
    de UTC). Toda resposta com campo de data deve herdar daqui em vez de
    BaseModel."""

    @model_validator(mode="after")
    def _marcar_datas_como_utc(self):
        for nome in type(self).model_fields:
            valor = getattr(self, nome)
            if isinstance(valor, datetime) and valor.tzinfo is None:
                setattr(self, nome, valor.replace(tzinfo=timezone.utc))
        return self


class LoginRequest(BaseModel):
    username: str
    senha: str


class LoginResponse(BaseModel):
    token: str
    papel: str
    unidade_id: Optional[int]
    nome: str
    pode_liberar_manualmente: bool


class LogoutRequest(BaseModel):
    token: str


class TrocarSenhaRequest(BaseModel):
    senha_atual: str  # confere posse da conta -- mesmo o dono precisa informar
    nova_senha: str


class UnidadeIn(BaseModel):
    nome: str
    tolerancia_padrao_minutos: int = 15
    valor_mensalidade: float = 200.0
    dias_validade_mensalidade: int = 30


class UnidadeUpdate(BaseModel):
    nome: Optional[str] = None
    ativo: Optional[bool] = None
    tolerancia_padrao_minutos: Optional[int] = None
    valor_mensalidade: Optional[float] = None
    dias_validade_mensalidade: Optional[int] = None


class UnidadeOut(BaseModel):
    id: int
    nome: str
    ativo: bool
    tolerancia_padrao_minutos: int
    valor_mensalidade: float
    dias_validade_mensalidade: int

    class Config:
        from_attributes = True


class ContaCriada(BaseModel):
    username: str
    senha: str  # texto puro -- só aparece aqui, na criação, nunca mais
    papel: str


class UnidadeCriadaResponse(BaseModel):
    unidade: UnidadeOut
    contas: list[ContaCriada]


class TicketOut(ComDatasUTC):
    id: int
    unidade_id: int
    codigo_barras: str
    data_hora_entrada: datetime
    data_hora_saida: Optional[datetime]
    status: str
    tempo_permanencia_minutos: Optional[int]
    tolerancia_aplicada_minutos: Optional[int]
    valor_calculado: float

    class Config:
        from_attributes = True


class ValidarCupomRequest(BaseModel):
    codigo_barras: str          # código do ticket, lido no totem de autoatendimento
    chave_acesso_nfce: str      # extraída do QR code da nota fiscal (44 dígitos)
    valor_compra: float
    data_hora_emissao: Optional[datetime] = None
    # cnpj_estabelecimento não é mais um campo de entrada: é derivado da
    # própria chave_acesso_nfce na validação, para não depender de um dado
    # que o totem poderia informar errado (ou falsificado).


class VerificarSaidaResponse(BaseModel):
    codigo_barras: str
    liberar_cancela: bool
    motivo: str
    tempo_permanencia_minutos: int
    tolerancia_aplicada_minutos: int
    valor_calculado: float


class PagamentoRequest(BaseModel):
    codigo_barras: str
    forma_pagamento: str  # pix | cartao | dinheiro
    valor: float


class CredenciadoIn(BaseModel):
    nome: str
    tipo: Literal["credenciado", "mensalista"]
    identificador_facial: str  # retornado pelo SDK de reconhecimento facial do totem
    documento: Optional[str] = None
    placa: Optional[str] = None
    empresa_vinculo: Optional[str] = None
    # Obrigatório para dono/gerente de operações (gerenciam várias
    # unidades); ignorado para supervisor, que só cadastra na própria.
    unidade_id: Optional[int] = None


class CredenciadoUpdate(BaseModel):
    nome: Optional[str] = None
    documento: Optional[str] = None
    placa: Optional[str] = None
    empresa_vinculo: Optional[str] = None
    ativo: Optional[bool] = None


class CredenciadoOut(ComDatasUTC):
    id: int
    unidade_id: int
    nome: str
    tipo: str
    identificador_facial: str
    documento: Optional[str]
    placa: Optional[str]
    empresa_vinculo: Optional[str]
    ativo: bool
    data_validade: Optional[datetime]

    class Config:
        from_attributes = True


class RenovarMensalidadeRequest(BaseModel):
    # None = usa o valor configurado na unidade do credenciado; informado
    # permite um ajuste pontual (ex: promoção).
    valor: Optional[float] = None
    forma_pagamento: str = "pix"


class IdentificacaoFacialRequest(BaseModel):
    identificador_facial: str  # retornado pelo SDK de reconhecimento facial do totem


class AcessoCredenciadoResponse(BaseModel):
    liberar_cancela: bool
    motivo: str
    credenciado_nome: str
    tipo: str
    ticket_id: Optional[int] = None


class TentativaCupomDuplicadoOut(ComDatasUTC):
    id: int
    unidade_id: int
    chave_acesso_nfce: str
    codigo_barras_tentativa: str
    ticket_original_id: Optional[int]
    data_hora: datetime

    class Config:
        from_attributes = True


class LiberacaoManualRequest(BaseModel):
    cancela: Literal["entrada", "saida"]
    motivo: str  # justificativa obrigatória, fica registrada na auditoria
    ticket_id: Optional[int] = None  # opcional: nem sempre existe um ticket válido
    # Só usado quando ticket_id não é informado (a unidade é derivada do
    # ticket quando ele existe). Obrigatório pra dono/gerente de operações
    # nesse caso; ignorado pra supervisor, que só libera na própria unidade.
    unidade_id: Optional[int] = None


class LiberacaoManualOut(ComDatasUTC):
    id: int
    unidade_id: int
    cancela: Optional[str]
    motivo: str
    ticket_id: Optional[int]
    via_limpeza_patio: bool
    usuario_nome: str
    data_hora: datetime

    class Config:
        from_attributes = True


class RegraToleranciaIn(BaseModel):
    # None = "qualquer cupom desse estabelecimento, sem valor mínimo"
    valor_minimo_compra: Optional[float] = None
    tolerancia_minutos: int


class RegraToleranciaOut(BaseModel):
    id: int
    valor_minimo_compra: Optional[float]
    tolerancia_minutos: int

    class Config:
        from_attributes = True


class EstabelecimentoIn(BaseModel):
    cnpj: str  # 14 dígitos, sem pontuação
    nome: str
    unidade_id: Optional[int] = None  # obrigatório pra dono/gerente de operações, ignorado pra supervisor


class EstabelecimentoUpdate(BaseModel):
    nome: Optional[str] = None
    ativo: Optional[bool] = None


class EstabelecimentoOut(BaseModel):
    id: int
    unidade_id: int
    cnpj: str
    nome: str
    ativo: bool
    regras_tolerancia: list[RegraToleranciaOut] = []

    class Config:
        from_attributes = True


class LimparPatioRequest(BaseModel):
    # Sem campo de cancela -- limpeza de pátio não abre nada fisicamente,
    # só finaliza tickets presos no sistema.
    motivo: str  # justificativa obrigatória, fica registrada por ticket afetado
    # Sempre obrigatório pra dono -- limpeza de pátio nunca vale pra "todas
    # as unidades" de uma vez, mesmo pra quem enxerga tudo.
    unidade_id: Optional[int] = None


class ExclusaoTicketRequest(BaseModel):
    motivo: str


class ExclusaoTicketOut(ComDatasUTC):
    id: int
    unidade_id: int
    codigo_barras: str
    motivo: str
    usuario_nome: str
    data_hora: datetime

    class Config:
        from_attributes = True


class ConciliacaoResponse(ComDatasUTC):
    """Achar a diferença entre tickets impressos, pagos e liberados.

    Isento (dentro da tolerância) não é "diferença" -- é o esperado. A
    diferença de verdade é `tickets_tarifados_sem_pagar`: excedeu a
    tolerância, devia pagar, saiu (ou foi liberado manualmente) sem pagar."""
    periodo_inicio: Optional[datetime]
    periodo_fim: datetime

    tickets_impressos: int
    tickets_liberados: int          # saíram (finalizado), de qualquer tipo
    tickets_tarifados: int          # excederam a tolerância, deviam pagar
    tickets_tarifados_pagos: int
    tickets_tarifados_sem_pagar: int  # a diferença de verdade -- provável furo

    valor_esperado: float    # soma do valor_calculado dos tickets tarifados
    valor_recebido: float    # soma das transações de fato pagas
    diferenca_valor: float   # valor_esperado - valor_recebido

    valor_mensalidades: float
    por_forma_pagamento: dict


class DashboardResponse(ComDatasUTC):
    """Visão operacional: movimento no período + pátio em tempo real
    (contagem "agora", independente do filtro de período)."""
    periodo_inicio: Optional[datetime]
    periodo_fim: datetime

    entradas_no_periodo: int
    saidas_no_periodo: int
    acessos_credenciado_no_periodo: int
    acessos_mensalista_no_periodo: int

    veiculos_no_patio_agora: int
    veiculos_no_patio_credenciado: int
    veiculos_no_patio_mensalista: int

    por_forma_pagamento: dict


class UsuarioIn(BaseModel):
    nome: str
    papel: Literal[
        "dono", "gerente_operacoes", "supervisor", "operador",
        "totem_entrada", "totem_validacao", "totem_saida",
    ]
    # Obrigatório quando papel="operador" -- vira o username de login
    # (só dígitos). Para os demais papéis, o username é derivado do nome.
    cpf: Optional[str] = None
    # Obrigatório pra dono/gerente de operações criando supervisor/
    # operador/totem de uma unidade específica; ignorado (forçado pra
    # própria unidade) se quem cria é supervisor. Dono/gerente de
    # operações criando outro dono/gerente de operações não usa unidade
    # nenhuma -- os dois enxergam todas.
    unidade_id: Optional[int] = None
    pode_liberar_manualmente: bool = False
    # None = gera uma senha aleatória (mostrada uma vez na resposta, como
    # hoje). Informada = usa essa senha em vez de gerar -- útil quando
    # quem cria já quer combinar a senha com a pessoa na hora.
    senha: Optional[str] = None


class UsuarioOut(BaseModel):
    id: int
    username: str
    nome: str
    papel: str
    unidade_id: Optional[int]
    ativo: bool
    pode_liberar_manualmente: bool

    class Config:
        from_attributes = True


class UsuarioCriadoResponse(BaseModel):
    usuario: UsuarioOut
    senha: str  # texto puro -- só aparece aqui, na criação, nunca mais


class UsuarioUpdate(BaseModel):
    ativo: Optional[bool] = None
    pode_liberar_manualmente: Optional[bool] = None


class AuditoriaEvento(ComDatasUTC):
    """Formato unificado pros três tipos de evento de auditoria hoje
    existentes (liberação manual, exclusão de ticket, cupom duplicado) --
    e espaço pra outros tipos de falha que surgirem depois."""
    tipo: Literal["liberacao_manual", "exclusao_ticket", "cupom_duplicado"]
    descricao: str
    unidade_id: int
    usuario_nome: Optional[str] = None
    data_hora: datetime
    detalhes: dict = {}
