"""
Trava a tabela de tarifa real: 1ª hora R$10, +R$5 por hora adicional,
travando em R$35 até 12h; depois disso reinicia o ciclo.
"""
import pytest

from app.services import calcular_tarifa


@pytest.mark.parametrize("minutos, valor_esperado", [
    (1, 10.0),      # qualquer fração já cobra a 1ª hora
    (60, 10.0),     # 1h exata
    (61, 15.0),     # fração da 2ª hora já cobra a 2ª hora
    (120, 15.0),    # 2h exatas
    (300, 30.0),    # 5h exatas
    (301, 35.0),    # fração da 6ª hora já trava na diária
    (360, 35.0),    # 6h exatas
    (480, 35.0),    # 8h -- segue travado em R$35
    (720, 35.0),    # 12h exatas -- ainda a mesma diária
    (721, 45.0),    # 12h01 -- inicia novo ciclo: R$35 + R$10
    (780, 45.0),    # 13h -- exemplo dado: 1 diária (35) + 1ª hora (10)
    (781, 50.0),    # 13h01 -- exemplo dado: já entra na 2ª hora do novo ciclo (35 + 15)
    (1500, 80.0),   # 25h -- 2 diárias completas (70) + 1ª hora do 3º ciclo (10)
])
def test_calcular_tarifa(minutos, valor_esperado):
    assert calcular_tarifa(minutos) == valor_esperado
