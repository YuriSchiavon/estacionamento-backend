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
    chave_acesso_nfce: str      # extraída do QR code da nota fiscal
    valor_compra: float
    cnpj_estabelecimento: Optional[str] = None
    data_hora_emissao: Optional[datetime] = None


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
