from .database import SessionLocal, engine, Base
from . import models

# Regra padrão global: aplicada quando não há cupom fiscal nenhum, para
# qualquer entrada, independente de estabelecimento conveniado.
REGRA_PADRAO_GLOBAL = dict(valor_minimo_compra=None, tolerancia_minutos=15)

# Estabelecimento conveniado seed -- representa o contrato atual (o
# supermercado). O CNPJ abaixo é só um placeholder: TROQUE pelo CNPJ real
# assim que souber, pelo painel de gestão (/gestao) -- sem isso, nenhum
# cupom desse estabelecimento vai validar (a chave da NFC-e real vai trazer
# um CNPJ diferente do cadastrado aqui).
CNPJ_PLACEHOLDER = "00000000000000"
NOME_ESTABELECIMENTO_PADRAO = "Supermercado (ATUALIZAR CNPJ no painel de gestão)"

REGRAS_ESTABELECIMENTO_PADRAO = [
    dict(valor_minimo_compra=0.01, tolerancia_minutos=30),   # qualquer cupom
    dict(valor_minimo_compra=45.00, tolerancia_minutos=60),
    dict(valor_minimo_compra=90.00, tolerancia_minutos=90),
    dict(valor_minimo_compra=150.00, tolerancia_minutos=360),
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.RegraTolerancia).count() == 0:
            db.add(models.RegraTolerancia(**REGRA_PADRAO_GLOBAL))

            estabelecimento = models.Estabelecimento(
                cnpj=CNPJ_PLACEHOLDER, nome=NOME_ESTABELECIMENTO_PADRAO
            )
            db.add(estabelecimento)
            db.flush()  # garante estabelecimento.id antes de usar como FK

            for regra in REGRAS_ESTABELECIMENTO_PADRAO:
                db.add(models.RegraTolerancia(estabelecimento_id=estabelecimento.id, **regra))

            db.commit()
            print("Regras de tolerância e estabelecimento padrão inseridos.")
            print(
                f"AVISO: estabelecimento '{NOME_ESTABELECIMENTO_PADRAO}' usando CNPJ "
                f"placeholder ({CNPJ_PLACEHOLDER}) -- troque pelo CNPJ real no painel "
                f"de gestão (/gestao) antes de ir para produção, ou nenhum cupom vai validar."
            )
        else:
            print("Regras de tolerância já existentes, nada a fazer.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
