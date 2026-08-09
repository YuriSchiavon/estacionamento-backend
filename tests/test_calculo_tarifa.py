"""
Trava a tabela de tarifa (agora configurável por unidade, ver
app/services.py calcular_tarifa): 1ª hora R$10, +R$5 por hora adicional,
travando em R$35 até 12h; depois disso reinicia o ciclo. Os valores
default usados aqui reproduzem a tabela real (MY PARK) que já era fixa
no código antes de virar configurável por unidade.
"""
import pytest

from app.services import calcular_tarifa

VALOR_PRIMEIRA_HORA = 10.0
INCREMENTO_POR_HORA = 5.0
VALOR_DIARIA = 35.0


def _tarifa(minutos, granularidade="hora_cheia"):
    return calcular_tarifa(minutos, VALOR_PRIMEIRA_HORA, INCREMENTO_POR_HORA, VALOR_DIARIA, granularidade)


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
def test_calcular_tarifa_hora_cheia(minutos, valor_esperado):
    assert _tarifa(minutos) == valor_esperado


@pytest.mark.parametrize("minutos, valor_esperado", [
    (1, 2.5),       # qualquer fração do 1º quarto de hora já cobra ele inteiro (10/4)
    (15, 2.5),      # 15 min exatos -- 1 bloco
    (16, 5.0),      # fração do 2º bloco -- 2 blocos inteiros da 1ª hora (2 * 2.5)
    (45, 7.5),      # 3 blocos da 1ª hora
    (60, 10.0),     # 1h exata -- 4 blocos = mesmo valor da hora cheia
    (61, 11.25),    # fração do 5º bloco -- 1ª hora inteira (10) + 1 bloco da 2ª hora (5/4)
    (120, 15.0),    # 2h exatas -- mesmo valor da hora cheia pra 2h
    (360, 35.0),    # 6h exatas -- mesmo teto da diária de sempre
])
def test_calcular_tarifa_fracao_15min(minutos, valor_esperado):
    assert _tarifa(minutos, "fracao_15min") == valor_esperado


def test_calcular_tarifa_respeita_valores_customizados_por_unidade():
    # unidade com preço bem diferente do padrão -- 1ª hora R$20, +R$8/h, teto R$60
    assert calcular_tarifa(60, 20.0, 8.0, 60.0, "hora_cheia") == 20.0
    assert calcular_tarifa(120, 20.0, 8.0, 60.0, "hora_cheia") == 28.0
    assert calcular_tarifa(600, 20.0, 8.0, 60.0, "hora_cheia") == 60.0  # travado no teto
