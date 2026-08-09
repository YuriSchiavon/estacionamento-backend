"""
Migração leve, sem Alembic -- o projeto usa Base.metadata.create_all, que
só cria tabelas que ainda não existem, nunca adiciona coluna numa tabela
já existente. Toda vez que um campo novo é adicionado a um model cuja
tabela já existe em produção, ele precisa entrar aqui também, senão o
banco de produção (que já tinha a tabela antes) fica sem a coluna e o
app derruba no startup com "column does not exist".

Roda uma vez a cada startup, antes do create_all; é idempotente (só
executa o ALTER se a coluna ainda não existir) -- seguro rodar sempre.
Bancos novos (create_all cria a tabela do zero, já com a coluna) não são
afetados: has_table() retorna False e a entrada é pulada.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# (tabela, coluna, tipo+default usado só no ALTER -- não precisa bater
# 100% com o tipo do model, só ser compatível o bastante pro SQLAlchemy
# ler/escrever via bind params; tipos genéricos funcionam tanto em
# Postgres quanto em SQLite)
_COLUNAS_NOVAS = [
    ("unidades", "valor_primeira_hora", "FLOAT DEFAULT 10.0"),
    ("unidades", "incremento_por_hora", "FLOAT DEFAULT 5.0"),
    ("unidades", "valor_diaria", "FLOAT DEFAULT 35.0"),
    ("unidades", "granularidade_cobranca", "VARCHAR DEFAULT 'hora_cheia'"),
    ("unidades", "funcionamento_24h", "BOOLEAN DEFAULT TRUE"),
    ("unidades", "horario_abertura", "TIME"),
    ("unidades", "horario_fechamento", "TIME"),
    ("unidades", "ticket_texto_extra", "VARCHAR"),
    ("unidades", "imprimir_automaticamente", "BOOLEAN DEFAULT TRUE"),
    ("unidades", "permite_pre_pagamento", "BOOLEAN DEFAULT FALSE"),
    ("unidades", "valor_pre_pagamento", "FLOAT"),
    ("estabelecimentos", "tipo_beneficio", "VARCHAR DEFAULT 'tolerancia'"),
    ("tickets", "pre_pago", "BOOLEAN DEFAULT FALSE"),
]


def migrar_colunas_novas(engine: Engine):
    inspector = inspect(engine)
    with engine.begin() as conn:
        for tabela, coluna, definicao in _COLUNAS_NOVAS:
            if not inspector.has_table(tabela):
                continue
            colunas_existentes = {c["name"] for c in inspector.get_columns(tabela)}
            if coluna in colunas_existentes:
                continue
            conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}"))
