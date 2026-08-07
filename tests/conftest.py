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
from app.seed import REGRA_PADRAO_GLOBAL, REGRAS_ESTABELECIMENTO_PADRAO
from app.security import (
    exigir_chave_entrada,
    exigir_chave_gestao,
    exigir_chave_liberacao_manual,
    exigir_chave_saida,
    exigir_chave_validacao,
)
from app import models

# CNPJ fictício (formato válido, comumente usado como exemplo em tutoriais)
# usado como o estabelecimento conveniado "padrão" nos testes.
CNPJ_ESTABELECIMENTO_TESTE = "11222333000181"


def fabricar_chave_nfce(cnpj: str, sufixo="1") -> str:
    """Monta uma chave de acesso de NFC-e (44 dígitos) com o CNPJ informado
    embutido nas posições certas -- simula o que viria do QR code real.
    `sufixo` varia o número da nota para gerar chaves únicas nos testes."""
    sufixo = str(sufixo).zfill(9)[-9:]
    return f"35" f"2508" f"{cnpj:0>14}" f"65" f"001" f"{sufixo}" f"1" f"12345678" f"9"

# Estes testes cobrem regra de negócio, não autenticação -- a autenticação
# em si é testada isoladamente em tests/test_autenticacao.py.
app.dependency_overrides[exigir_chave_entrada] = lambda: None
app.dependency_overrides[exigir_chave_validacao] = lambda: None
app.dependency_overrides[exigir_chave_saida] = lambda: None
app.dependency_overrides[exigir_chave_gestao] = lambda: None
app.dependency_overrides[exigir_chave_liberacao_manual] = lambda: None

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

    db.add(models.RegraTolerancia(**REGRA_PADRAO_GLOBAL))

    estabelecimento = models.Estabelecimento(cnpj=CNPJ_ESTABELECIMENTO_TESTE, nome="Estabelecimento Teste")
    db.add(estabelecimento)
    db.flush()
    for regra in REGRAS_ESTABELECIMENTO_PADRAO:
        db.add(models.RegraTolerancia(estabelecimento_id=estabelecimento.id, **regra))

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
