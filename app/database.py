import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

# Local/prototipo: SQLite em arquivo (padrão se DATABASE_URL não for definida).
# Produção: defina DATABASE_URL no ambiente (ou no .env) apontando para o
# Postgres/MySQL escolhido -- o resto do código não muda. Ver .env.example.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./estacionamento.db")

# SQLite exige essa flag para funcionar com múltiplas conexões/threads;
# Postgres e MySQL não usam (e não aceitam) esse argumento.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
