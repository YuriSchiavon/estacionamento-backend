"""
Leitura da chave de acesso da NFC-e (44 dígitos, padrão SEFAZ).

O CNPJ do estabelecimento emissor vem embutido nas posições 7-20 da própria
chave -- não depende de nenhum dado declarado pelo totem, então não dá pra
falsificar sem invalidar a chave inteira. É isso que usamos para conferir
se o cupom veio mesmo de um estabelecimento conveniado.

Estrutura da chave (44 dígitos): cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3)
nNF(9) tpEmis(1) cNF(8) cDV(1) = 44.
"""
import re

CHAVE_REGEX = re.compile(r"^\d{44}$")


def extrair_cnpj_emitente(chave_acesso_nfce: str) -> str:
    """Retorna o CNPJ (14 dígitos) embutido na chave. Levanta ValueError se
    a chave não tiver o formato de 44 dígitos numéricos esperado."""
    if not CHAVE_REGEX.match(chave_acesso_nfce or ""):
        raise ValueError("Chave de acesso da NFC-e inválida: precisa ter 44 dígitos numéricos")
    return chave_acesso_nfce[6:20]
