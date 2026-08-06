from .database import SessionLocal, engine, Base
from . import models

REGRAS = [
    dict(valor_minimo_compra=None, tolerancia_minutos=15),   # sem cupom
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
            for r in REGRAS:
                db.add(models.RegraTolerancia(**r))
            db.commit()
            print("Regras de tolerância inseridas.")
        else:
            print("Regras de tolerância já existentes, nada a fazer.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
