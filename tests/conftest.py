"""
Configuração dos testes: usa um banco SQLite em memória, isolado do
`estacionamento.db` real, recriado do zero antes de cada teste.

Os testes de regra de negócio usam um usuário de teste fixo (papel
supervisor, preso a uma unidade de teste) via dependency_overrides -- não
testam o login de verdade. Login e isolamento entre unidades são testados
à parte, sem esse bypass (ver test_autenticacao.py e test_unidades.py).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, get_db
from app.seed import REGRAS_ESTABELECIMENTO_PADRAO
from app.security import (
    exigir_gestao,
    exigir_liberacao_manual,
    exigir_operacao,
    exigir_totem_entrada,
    exigir_totem_saida,
    exigir_totem_validacao,
    exigir_totem_validacao_ou_saida,
)
from app import models

CNPJ_ESTABELECIMENTO_TESTE = "11222333000181"
UNIDADE_TESTE_ID = 1


def fabricar_chave_nfce(cnpj: str, sufixo="1") -> str:
    """Monta uma chave de acesso de NFC-e (44 dígitos) com o CNPJ informado
    embutido nas posições certas -- simula o que viria do QR code real.
    `sufixo` varia o número da nota para gerar chaves únicas nos testes."""
    sufixo = str(sufixo).zfill(9)[-9:]
    return f"35" f"2508" f"{cnpj:0>14}" f"65" f"001" f"{sufixo}" f"1" f"12345678" f"9"


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

# Usuário de teste fixo: supervisor da unidade de teste, com permissão de
# liberação manual -- cobre o caso comum sem precisar de unidade_id
# explícito em cada payload (supervisor nunca sai da própria unidade,
# então fica implícito). É um objeto transiente, nunca gravado no banco --
# só serve pra passar pelos `Depends`, os testes não olham pra ele além disso.
_usuario_teste = models.Usuario(
    id=999, username="teste", nome="Usuário de Teste",
    papel=models.PapelUsuario.supervisor, unidade_id=UNIDADE_TESTE_ID,
    pode_liberar_manualmente=True, ativo=True,
)

app.dependency_overrides[exigir_totem_entrada] = lambda: _usuario_teste
app.dependency_overrides[exigir_totem_validacao] = lambda: _usuario_teste
app.dependency_overrides[exigir_totem_validacao_ou_saida] = lambda: _usuario_teste
app.dependency_overrides[exigir_totem_saida] = lambda: _usuario_teste
app.dependency_overrides[exigir_gestao] = lambda: _usuario_teste
app.dependency_overrides[exigir_operacao] = lambda: _usuario_teste
app.dependency_overrides[exigir_liberacao_manual] = lambda: _usuario_teste


@pytest.fixture(autouse=True)
def banco_limpo():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    unidade = models.Unidade(id=UNIDADE_TESTE_ID, nome="Unidade Teste", tolerancia_padrao_minutos=15)
    db.add(unidade)
    db.flush()

    estabelecimento = models.Estabelecimento(
        unidade_id=unidade.id, cnpj=CNPJ_ESTABELECIMENTO_TESTE, nome="Estabelecimento Teste"
    )
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


@pytest.fixture
def client_com_autenticacao_real():
    """Remove temporariamente o bypass de autenticação -- usado pelos
    testes que precisam do fluxo de login de verdade (token, papel,
    isolamento entre unidades), não da regra de negócio em si."""
    dependencias = (
        exigir_totem_entrada, exigir_totem_validacao, exigir_totem_validacao_ou_saida, exigir_totem_saida,
        exigir_gestao, exigir_operacao, exigir_liberacao_manual,
    )
    salvos = {dep: app.dependency_overrides.pop(dep, None) for dep in dependencias}
    try:
        yield TestClient(app)
    finally:
        for dep, override in salvos.items():
            if override is not None:
                app.dependency_overrides[dep] = override
