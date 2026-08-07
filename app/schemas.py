from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class TicketOut(BaseModel):
    id: int
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


class CredenciadoUpdate(BaseModel):
    nome: Optional[str] = None
    documento: Optional[str] = None
    placa: Optional[str] = None
    empresa_vinculo: Optional[str] = None
    ativo: Optional[bool] = None


class CredenciadoOut(BaseModel):
    id: int
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
    valor: float = 200.0
    forma_pagamento: str = "pix"


class IdentificacaoFacialRequest(BaseModel):
    identificador_facial: str  # retornado pelo SDK de reconhecimento facial do totem


class AcessoCredenciadoResponse(BaseModel):
    liberar_cancela: bool
    motivo: str
    credenciado_nome: str
    tipo: str
    ticket_id: Optional[int] = None


class TentativaCupomDuplicadoOut(BaseModel):
    id: int
    chave_acesso_nfce: str
    codigo_barras_tentativa: str
    ticket_original_id: Optional[int]
    data_hora: datetime

    class Config:
        from_attributes = True


class RelatorioFinanceiroResponse(BaseModel):
    periodo_inicio: Optional[datetime]
    periodo_fim: datetime
    total_arrecadado: float
    por_forma_pagamento: dict
    quantidade_transacoes: int


class LiberacaoManualRequest(BaseModel):
    cancela: Literal["entrada", "saida"]
    motivo: str  # justificativa obrigatória, fica registrada na auditoria
    ticket_id: Optional[int] = None  # opcional: nem sempre existe um ticket válido


class LiberacaoManualOut(BaseModel):
    id: int
    cancela: str
    motivo: str
    ticket_id: Optional[int]
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


class EstabelecimentoUpdate(BaseModel):
    nome: Optional[str] = None
    ativo: Optional[bool] = None


class EstabelecimentoOut(BaseModel):
    id: int
    cnpj: str
    nome: str
    ativo: bool
    regras_tolerancia: list[RegraToleranciaOut] = []

    class Config:
        from_attributes = True
