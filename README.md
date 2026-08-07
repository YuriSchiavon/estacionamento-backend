# Estacionamento — Controle de Acesso (protótipo)

Protótipo do backend que implementa o fluxo e as regras de negócio que
desenhamos: entrada, validação de cupom fiscal por QR code (NFC-e) no
totem de autoatendimento, tolerância de permanência e liberação na
cancela de saída.

## Como rodar

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Depois abra `http://localhost:8000/docs` para o Swagger, ou
`http://localhost:8000/gestao` para o painel visual. Na primeira execução,
o sistema cria sozinho a unidade padrão, o usuário `dono` e as contas dos
totens — as senhas geradas aparecem uma vez no log do servidor
(`AVISO: login do dono -> ...`), anote antes de perder.

## Multi-unidade e login

O sistema atende várias unidades (estacionamentos) ao mesmo tempo — cada
uma com seus próprios tickets, credenciados e estabelecimentos conveniados.
Autenticação é por **login (usuário/senha)**, não chave de API fixa:

- **`dono`**: vê e gerencia todas as unidades (pode filtrar uma específica
  ou ver "geral", agregando tudo).
- **`gerente`**: preso a uma unidade só — nunca enxerga nem afeta dados de
  outra, mesmo tentando informar outro ID (o backend sempre ignora e usa a
  unidade do próprio usuário).
- **`totem_entrada` / `totem_validacao` / `totem_saida`**: uma conta por
  função, por unidade — é o que cada totem físico usa para logar.
- **`pode_liberar_manualmente`**: permissão elevada e independente do
  papel — só quem tem essa flag consegue liberar cancela manualmente ou
  limpar o pátio, mesmo sendo dono/gerente.

Login em `POST /auth/login` (usuário/senha) retorna um token opaco
(`Authorization: Bearer <token>`), revogável na hora em `POST /auth/logout`
(apaga a sessão do banco — não é JWT, não precisa de blocklist).

**Cadastrar uma unidade nova** (`POST /gestao/unidades`, só `dono`) já
cria as 3 contas de totem automaticamente — usuário e senha aparecem uma
única vez na resposta, anote e configure nos equipamentos.

Na primeira execução, o seed cria a unidade padrão, um usuário `dono`
(`admin`) e as 3 contas de totem dela, com senhas aleatórias impressas no
log (`AVISO: login do dono -> ...`) — troque depois de anotar.

## Endpoints e onde cada um se encaixa no fluxo

| Endpoint | Chamado por | O que faz |
|---|---|---|
| `POST /auth/login` | Qualquer conta | Login (usuário/senha), retorna token |
| `POST /auth/logout` | Qualquer conta | Revoga o token na hora |
| `POST /entrada` | Totem emissor | Cria o ticket, retorna o código de barras para impressão |
| `POST /loja/validar-cupom` | Totem de autoatendimento (após ler o QR code) | Vincula a nota fiscal ao ticket, garantindo unicidade da chave |
| `GET /saida/verificar/{codigo_barras}` | Totem leitor da cancela | Calcula permanência, aplica tolerância, decide se libera |
| `POST /saida/pagamento` | Totem de pagamento | Registra pagamento quando o valor excedeu a tolerância |
| `POST /credenciados/entrada` | Totem de entrada (leitura facial) | Reconhece credenciado/mensalista pelo identificador facial e libera entrada |
| `POST /credenciados/saida` | Totem de saída (leitura facial) | Libera a saída do credenciado/mensalista reconhecido |
| `POST /gestao/unidades` | Painel de gestão (dono) | Cadastra unidade + gera as 3 contas de totem dela |
| `GET /gestao/unidades` | Painel de gestão | Lista unidades (dono: todas; gerente: só a própria) |
| `PATCH /gestao/unidades/{id}` | Painel de gestão | Edita nome/tolerância padrão/ativa-desativa |
| `POST /gestao/credenciados` | Painel de gestão | Cadastra um credenciado ou mensalista |
| `GET /gestao/credenciados` | Painel de gestão | Lista credenciados/mensalistas |
| `PATCH /gestao/credenciados/{id}` | Painel de gestão | Edita dados / ativa / desativa |
| `POST /gestao/credenciados/{id}/renovar` | Painel de gestão | Registra pagamento de mensalidade (+30 dias) |
| `GET /gestao/relatorio/tickets` | Painel de gestão | Lista tickets por período |
| `GET /gestao/relatorio/conciliacao` | Painel de gestão | Diferença entre tickets impressos, pagos e liberados |
| `GET /gestao/dashboard` | Painel de gestão | Movimento no período + pátio em tempo real |
| `GET /gestao/relatorio/cupons-duplicados` | Painel de gestão | Auditoria de tentativas de reuso de cupom fiscal |
| `POST /gestao/liberacao-manual` | Painel de gestão | Libera uma cancela manualmente (fluxo automático falhou) |
| `GET /gestao/relatorio/liberacoes-manuais` | Painel de gestão | Auditoria de liberações manuais |
| `POST /gestao/liberacao-manual/limpar-patio` | Painel de gestão | Finaliza em massa todos os tickets em aberto de uma unidade |
| `POST /gestao/tickets/{id}/excluir` | Painel de gestão | Exclui um ticket avulso (sem pagamento registrado) |
| `GET /gestao/relatorio/exclusoes-tickets` | Painel de gestão | Auditoria de exclusões de ticket |
| `POST /gestao/estabelecimentos` | Painel de gestão | Cadastra um estabelecimento conveniado |
| `GET /gestao/estabelecimentos` | Painel de gestão | Lista estabelecimentos e suas regras de tolerância |
| `PATCH /gestao/estabelecimentos/{id}` | Painel de gestão | Edita dados / ativa / desativa |
| `POST /gestao/estabelecimentos/{id}/regras-tolerancia` | Painel de gestão | Adiciona uma faixa de tolerância ao estabelecimento |
| `DELETE /gestao/estabelecimentos/{id}/regras-tolerancia/{regra_id}` | Painel de gestão | Remove uma faixa de tolerância |

## Estabelecimentos conveniados (multi-contrato)

Pensado pra ir além de um único supermercado — shopping, condomínio
comercial, qualquer lugar com vários estabelecimentos participando do
mesmo estacionamento. Cada um cadastrado com seu próprio CNPJ **e seu
próprio regulamento de tolerância** (contratos diferentes, regras
diferentes — não tem tabela compartilhada).

Como funciona a validação: o CNPJ do emitente já vem embutido nos dígitos
7-20 da própria chave de acesso da NFC-e (padrão SEFAZ, 44 dígitos) — não
é um dado que o totem declara, é extraído da chave lida no QR code, então
não dá pra informar um CNPJ falso sem invalidar a chave inteira
(`app/nfce.py`). Se o CNPJ extraído não bater com nenhum estabelecimento
ativo cadastrado, o cupom é rejeitado (`403`) — cupom de fora não conta
pra tolerância.

**Cadastro 100% pelo painel de gestão** (`/gestao`, seção "Estabelecimentos
conveniados") — CNPJ, nome, ativar/desativar, e adicionar/remover faixas
de tolerância, sem precisar mexer em código.

**Importante:** o estabelecimento inserido automaticamente na primeira
execução (`app/seed.py`) usa um **CNPJ placeholder** (`00000000000000`)
representando o contrato atual do supermercado. O servidor avisa no log
até isso ser trocado pelo CNPJ real no painel — sem isso, nenhum cupom
desse estabelecimento vai validar de verdade.

## Liberação manual de cancela (uso excepcional)

Existe pra cobrir os casos em que o fluxo automático falha (totem travou,
ticket não foi emitido, leitor com defeito) — abre a cancela na mão, pelo
painel de gestão, sem depender de um ticket válido existir. Também dá pra
**limpar o pátio inteiro** de uma vez (todos os tickets em aberto de uma
unidade) ou **excluir um ticket avulso** (duplicado por engano, sem
pagamento registrado).

Proteções de propósito, por ser uma ação com efeito físico real:

- **Permissão elevada e separada do papel** (`pode_liberar_manualmente`)
  — dono ou gerente sem essa flag não consegue acionar, mesmo logado.
- **Motivo obrigatório** e **registro de auditoria** (`app/models.py`
  `LiberacaoManual` / `ExclusaoTicket`) — toda ação fica rastreada: qual
  cancela, por quê, quando, e o ticket relacionado (se houver — o vínculo
  é opcional, já que às vezes o próprio ticket é o motivo da falha).
- **Limpeza de pátio nunca é "geral"** — sempre exige uma unidade
  explícita, mesmo pra dono, pra evitar limpar todas de uma vez por engano.

## Credenciados e mensalistas (acesso por reconhecimento facial)

Pensado para o totem com câmera facial (ex: Gertec SK315): a pessoa é
reconhecida pela câmera e libera acesso sem precisar de ticket físico.
Dois tipos, cadastrados em `/gestao/credenciados`:

- **Credenciado**: acesso 100% liberado, sempre, sem custo (ex: parceiro/convênio).
- **Mensalista**: paga R$200,00 e tem 30 dias de acesso liberado. Ao vencer,
  o acesso é bloqueado até renovar (`POST /gestao/credenciados/{id}/renovar`).
  Renovar antes de vencer soma os dias à validade atual — não perde dias
  pagos antecipadamente. Regras em `app/credenciamento.py`.

O `identificador_facial` é o valor que o SDK de reconhecimento facial do
totem retorna ao identificar a pessoa — ainda não integrado (depende da
resposta da Gertec sobre o SDK do SK315), mas o backend já está pronto
para recebê-lo.

## Regras já implementadas

- Sem cupom: tolerância padrão da unidade (`Unidade.tolerancia_padrao_minutos`, 15 min por padrão).
- Cupom de estabelecimento conveniado: cada um define suas próprias faixas por valor de compra (ex: R$45→60min, R$90→90min, R$150→360min) — configurável pelo painel, sem tocar em código.
- É tolerância, não gratuidade: passou do limite, cobra a permanência inteira.
- Chave de acesso da NFC-e é `UNIQUE` no banco — impede reuso do mesmo cupom.

## Painéis

- **`http://localhost:8000/`** — painel de testes dos totens: login por
  totem (entrada/validação/saída), emitir ticket, validar cupom, verificar
  saída, registrar pagamento e simular o acesso facial de credenciados/
  mensalistas, tudo clicando em botões.
- **`http://localhost:8000/gestao`** — painel de gestão: login, cadastro
  de unidades (dono), estabelecimentos conveniados, credenciados/
  mensalistas, dashboard operacional, conciliação financeira e auditorias.
  Dono vê um seletor pra filtrar por unidade ou ver "geral"; gerente fica
  preso à própria unidade automaticamente.

## O que falta para virar sistema de produção (próximos passos com o Claude Code)

1. **Driver de hardware**: escrever o adapter que fala o protocolo real de
   cada equipamento (TCP/IP, webhook, SDK) e chama esses endpoints. Isso
   depende da documentação técnica que os fornecedores vão te passar.
2. ~~**Cálculo de tarifa real**~~ ✅ `services.calcular_tarifa()` já usa a
   tabela real: R$10 a 1ª hora, +R$5 por hora adicional, travando em R$35
   até 12h (diária); depois disso o ciclo reinicia.
3. **Meio de pagamento**: `/saida/pagamento` hoje só registra manualmente —
   falta integrar um gateway (PIX, cartão) de verdade.
4. ~~**Autenticação/autorização**~~ ✅ login por usuário/senha (`POST
   /auth/login`), com contas por unidade e por função (totem_entrada/
   validacao/saida) ou por pessoa (dono/gerente). Ver `app/security.py`,
   `app/auth.py` e a seção "Multi-unidade e login" acima.
5. ~~**Trocar SQLite por Postgres/MySQL**~~ ✅ o código já lê `DATABASE_URL`
   do ambiente (ver `.env.example`) — sem SQLite continua sendo usado por
   padrão. Falta só **escolher onde hospedar** (Postgres é a recomendação;
   um serviço gerenciado tipo Railway/Supabase/Neon evita ter que
   administrar servidor de banco) e instalar o driver correspondente
   (`psycopg2-binary` ou `pymysql`, comentados no `requirements.txt`).
6. ~~**Testes automatizados**~~ ✅ `tests/` cobre os cenários de tolerância,
   a tabela de tarifa, login/papéis, isolamento entre unidades, o fluxo de
   credenciados/mensalistas e a manutenção do pátio. Rodar com
   `python -m pytest tests/ -v` (dependências de teste em
   `requirements-dev.txt`). 76 testes no total.
7. ~~**Painel de gestão**~~ ✅ `http://localhost:8000/gestao` — unidades,
   estabelecimentos conveniados, credenciados/mensalistas, dashboard,
   conciliação financeira e auditorias. Ver `app/rotas_gestao.py`.

Este protótipo não foi testado contra o ambiente de execução real (o
ambiente usado para criá-lo não tem acesso à internet para instalar as
dependências) — a sintaxe foi validada, mas rode os testes acima assim
que instalar as dependências, antes de seguir com a integração de hardware.
