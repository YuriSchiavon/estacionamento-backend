"""
Configuração dos testes: usa um banco SQLite em memória, isolado do
`estacionamento.db` real, e recriado do zero antes de cada teste.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.seed import REGRAS
from app.security import exigir_chave_entrada, exigir_chave_gestao, exigir_chave_saida, exigir_chave_validacao
from app import models

# Estes testes cobrem regra de negócio, não autenticação -- a autenticação
# em si é testada isoladamente em tests/test_autenticacao.py.
app.dependency_overrides[exigir_chave_entrada] = lambda: None
app.dependency_overrides[exigir_chave_validacao] = lambda: None
app.dependency_overrides[exigir_chave_saida] = lambda: None
app.dependency_overrides[exigir_chave_gestao] = lambda: None

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    for regra in REGRAS:
        db.add(models.RegraTolerancia(**regra))
    db.commit()
    db.close()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
