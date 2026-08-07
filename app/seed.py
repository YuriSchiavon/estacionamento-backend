from .auth import criar_usuario, gerar_senha_temporaria, slugify, username_disponivel
from .database import SessionLocal, engine, Base
from . import models

NOME_UNIDADE_PADRAO = "Unidade Padrão (ATUALIZAR)"
TOLERANCIA_PADRAO_MINUTOS = 15

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

USERNAME_DONO_PADRAO = "admin"


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(models.Unidade).count() > 0:
            print("Dados iniciais já existentes, nada a fazer.")
            return

        unidade = models.Unidade(nome=NOME_UNIDADE_PADRAO, tolerancia_padrao_minutos=TOLERANCIA_PADRAO_MINUTOS)
        db.add(unidade)
        db.flush()

        estabelecimento = models.Estabelecimento(
            unidade_id=unidade.id, cnpj=CNPJ_PLACEHOLDER, nome=NOME_ESTABELECIMENTO_PADRAO
        )
        db.add(estabelecimento)
        db.flush()
        for regra in REGRAS_ESTABELECIMENTO_PADRAO:
            db.add(models.RegraTolerancia(estabelecimento_id=estabelecimento.id, **regra))

        senha_dono = gerar_senha_temporaria()
        criar_usuario(
            db, USERNAME_DONO_PADRAO, senha_dono, "Administrador",
            models.PapelUsuario.dono, pode_liberar_manualmente=True,
        )

        slug = slugify(NOME_UNIDADE_PADRAO)
        contas_totem = []
        for papel, sufixo in (
            (models.PapelUsuario.totem_entrada, "entrada"),
            (models.PapelUsuario.totem_validacao, "validacao"),
            (models.PapelUsuario.totem_saida, "saida"),
        ):
            username = username_disponivel(db, f"{slug}-{sufixo}")
            senha = gerar_senha_temporaria()
            criar_usuario(db, username, senha, f"Totem {sufixo} - {NOME_UNIDADE_PADRAO}", papel, unidade_id=unidade.id)
            contas_totem.append((username, senha))

        db.commit()

        print("Unidade padrão, estabelecimento e usuários iniciais criados.")
        print(f"AVISO: login do dono -> usuário '{USERNAME_DONO_PADRAO}', senha '{senha_dono}' -- ANOTE e troque depois.")
        for username, senha in contas_totem:
            print(f"  Conta de totem -> usuário '{username}', senha '{senha}'")
        print(
            f"AVISO: estabelecimento '{NOME_ESTABELECIMENTO_PADRAO}' usando CNPJ "
            f"placeholder ({CNPJ_PLACEHOLDER}) -- troque pelo CNPJ real no painel "
            f"de gestão (/gestao) antes de ir para produção, ou nenhum cupom vai validar."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
