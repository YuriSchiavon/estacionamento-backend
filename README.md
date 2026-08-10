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
- **`operador`**: estacionamento assistido — uma pessoa loga e faz na mão
  o que o totem faria sozinho (emitir ticket, validar cupom, verificar
  saída, pagamento, consultar ticket). Sem acesso a credenciados,
  estabelecimentos, unidades ou usuários — isso continua exclusivo de
  dono/gerente.
- **`totem_entrada` / `totem_validacao` / `totem_saida`**: uma conta por
  função, por unidade — é o que cada totem físico usa para logar.
- **`pode_liberar_manualmente`**: permissão elevada e independente do
  papel — só quem tem essa flag consegue liberar cancela manualmente ou
  limpar o pátio, mesmo sendo dono/gerente/operador.

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
| `POST /entrada` | Totem emissor (ou operador) | Cria o ticket, retorna o código de barras para impressão |
| `POST /loja/validar-cupom` | Totem de autoatendimento, totem de saída ou operador | Vincula a nota fiscal ao ticket, garantindo unicidade da chave. Funciona com o ticket ainda `aberto` (loja) ou já `tarifado` (revalidação na cancela de saída) |
| `GET /saida/verificar/{codigo_barras}` | Totem leitor da cancela (ou operador) | Calcula permanência, aplica tolerância, decide se libera |
| `POST /saida/pagamento` | Totem de validação, totem de saída (caminho alternativo) ou operador | Registra pagamento quando o valor excedeu a tolerância |
| `POST /credenciados/entrada` | Totem de entrada (leitura facial) | Reconhece credenciado/mensalista pelo identificador facial e libera entrada |
| `POST /credenciados/saida` | Totem de saída (leitura facial) | Libera a saída do credenciado/mensalista reconhecido |
| `POST /gestao/unidades` | Painel de gestão (dono) | Cadastra unidade (com mensalidade/tolerância próprias) + gera as 3 contas de totem dela |
| `GET /gestao/unidades` | Painel de gestão | Lista unidades (dono: todas; gerente: só a própria) |
| `PATCH /gestao/unidades/{id}` | Painel de gestão | Edita nome/tolerância padrão/mensalidade/ativa-desativa |
| `POST /gestao/usuarios` | Painel de gestão | Cria uma conta avulsa (dono: qualquer papel/unidade; gerente: só operador da própria unidade) |
| `GET /gestao/usuarios` | Painel de gestão | Lista usuários (escopado por unidade) |
| `PATCH /gestao/usuarios/{id}` | Painel de gestão | Ativa/desativa e alterna `pode_liberar_manualmente` |
| `POST /gestao/credenciados` | Painel de gestão | Cadastra um credenciado ou mensalista |
| `GET /gestao/credenciados` | Painel de gestão | Lista credenciados/mensalistas |
| `PATCH /gestao/credenciados/{id}` | Painel de gestão | Edita dados / ativa / desativa |
| `POST /gestao/credenciados/{id}/renovar` | Painel de gestão | Registra pagamento de mensalidade (valor/dias configurados na unidade, ou um valor pontual informado) |
| `GET /gestao/relatorio/tickets` | Painel de gestão ou operador | Lista tickets por período |
| `GET /gestao/relatorio/conciliacao` | Painel de gestão | Diferença entre tickets impressos, pagos e liberados |
| `GET /gestao/dashboard` | Painel de gestão | Movimento no período + pátio em tempo real |
| `GET /gestao/relatorio/auditoria` | Painel de gestão | Auditoria unificada: liberações manuais, limpezas de pátio, exclusões de ticket e cupons duplicados, com filtro por tipo |
| `GET /gestao/relatorio/cupons-duplicados` | Painel de gestão | Auditoria de tentativas de reuso de cupom fiscal (também aparece em `/gestao/relatorio/auditoria`) |
| `POST /gestao/liberacao-manual` | Painel de gestão | Libera uma cancela manualmente (fluxo automático falhou) |
| `GET /gestao/relatorio/liberacoes-manuais` | Painel de gestão | Auditoria de liberações manuais (também aparece em `/gestao/relatorio/auditoria`) |
| `POST /gestao/liberacao-manual/limpar-patio` | Painel de gestão | Finaliza em massa todos os tickets em aberto de uma unidade — não abre cancela nenhuma |
| `POST /gestao/tickets/{id}/excluir` | Painel de gestão | Exclui um ticket avulso (sem pagamento registrado) |
| `GET /gestao/relatorio/exclusoes-tickets` | Painel de gestão | Auditoria de exclusões de ticket (também aparece em `/gestao/relatorio/auditoria`) |
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
painel de gestão ou pela tela de operação, sem depender de um ticket
válido existir. Também dá pra **limpar o pátio inteiro** de uma vez
(finaliza todos os tickets em aberto de uma unidade — não abre cancela
nenhuma, só zera o que ficou preso no sistema) ou **excluir um ticket
avulso** (duplicado por engano, sem pagamento registrado).

Proteções de propósito, por ser uma ação com efeito físico real:

- **Permissão elevada e separada do papel** (`pode_liberar_manualmente`)
  — dono, gerente ou operador sem essa flag não consegue acionar, mesmo
  logado.
- **Motivo obrigatório** e **quem fez fica registrado** (`app/models.py`
  `LiberacaoManual` / `ExclusaoTicket` guardam `usuario_nome`) — toda ação
  fica rastreada: qual cancela (quando aplicável), por quê, quando, quem,
  e o ticket relacionado (se houver — o vínculo é opcional, já que às
  vezes o próprio ticket é o motivo da falha). Tudo aparece junto em
  `GET /gestao/relatorio/auditoria`.
- **Limpeza de pátio nunca é "geral"** — sempre exige uma unidade
  explícita, mesmo pra dono, pra evitar limpar todas de uma vez por engano.

## Credenciados e mensalistas (acesso por reconhecimento facial)

Pensado para o totem com câmera facial (ex: Gertec SK315): a pessoa é
reconhecida pela câmera e libera acesso sem precisar de ticket físico.
Dois tipos, cadastrados em `/gestao/credenciados`:

- **Credenciado**: acesso 100% liberado, sempre, sem custo (ex: parceiro/convênio).
- **Mensalista**: paga o valor e tem os dias de acesso liberado
  **configurados por unidade** (`Unidade.valor_mensalidade` /
  `dias_validade_mensalidade`, editável em `/gestao/unidades` — contratos
  diferentes, preços diferentes). Ao vencer, o acesso é bloqueado até
  renovar (`POST /gestao/credenciados/{id}/renovar`, valor opcional para
  um ajuste pontual, ex. promoção). Renovar antes de vencer soma os dias
  à validade atual — não perde dias pagos antecipadamente. Regras em
  `app/credenciamento.py`.

O `identificador_facial` é o valor que o SDK de reconhecimento facial do
totem retorna ao identificar a pessoa — ainda não integrado (depende da
resposta da Gertec sobre o SDK do SK315), mas o backend já está pronto
para recebê-lo.

## Regras já implementadas

- Sem cupom: tolerância padrão da unidade (`Unidade.tolerancia_padrao_minutos`, 15 min por padrão).
- Cupom de estabelecimento conveniado: cada um define suas próprias faixas por valor de compra (ex: R$45→60min, R$90→90min, R$150→360min) — configurável pelo painel, sem tocar em código.
- É tolerância, não gratuidade: passou do limite, cobra a permanência inteira.
- Chave de acesso da NFC-e é `UNIQUE` no banco — impede reuso do mesmo cupom.

## Páginas

Três tipos de superfície, cada uma com seu propósito:

- **`http://localhost:8000/`** — landing: links para todas as páginas
  abaixo.
- **`http://localhost:8000/gestao`** — **painel gerencial** (dono/gerente):
  cadastro de unidades (dono, com mensalidade/tolerância próprias),
  estabelecimentos conveniados, credenciados/mensalistas, usuários,
  dashboard operacional, conciliação financeira e auditoria unificada.
  Dono vê um seletor pra filtrar por unidade ou ver "geral"; gerente fica
  preso à própria unidade automaticamente.
- **`http://localhost:8000/operacao`** — **login de operador** (CPF +
  senha, unidade já presa na conta): tela única com as ações do dia a dia
  de um estacionamento assistido — emitir ticket, validar cupom, verificar
  saída, pagamento, liberação manual (se tiver a permissão) e consulta de
  ticket. Sem acesso a nada de configuração.
- **`http://localhost:8000/totem/entrada`**,
  **`/totem/saida`**, **`/totem/validacao`** — as telas reais de cada
  equipamento físico: login uma vez (fica salvo no aparelho), depois só a
  ação daquele totem. Totem de saída controla a cancela -- foco em
  "apresente o ticket", com validar cupom/pagar como páginas de
  contingência caso o ticket não esteja liberado. Totem de validação não
  controla cancela nenhuma -- valida cupom fiscal (leitura automática do
  QR code da NFC-e, sem digitação) e processa pagamento, tipicamente
  posicionado antes da fila da cancela pra agilizar o fluxo.
- **`http://localhost:8000/simulador-totens`** — ambiente de
  desenvolvimento: os 5 totens (entrada/validação/saída/pagamento/facial)
  numa página só, com histórico de sessão, para testar o fluxo completo
  sem precisar do equipamento físico. Ainda simula entrada, validação e
  pagamento como painéis separados -- não reflete a fusão desses dois
  últimos no totem de Validação (`/totem/validacao`), que é a tela real.

## Deploy para teste remoto (Railway)

Pra deixar um link público estável, testável por qualquer pessoa fora da
sua rede (sem depender do seu computador ligado), a forma mais rápida é a
[Railway](https://railway.app):

1. **Suba este repositório para o GitHub** (se ainda não estiver lá).
2. Na Railway, crie um projeto novo → **"Deploy from GitHub repo"** →
   selecione este repositório. Ela detecta o `Procfile` sozinha.
3. No mesmo projeto, clique em **"+ New" → "Database" → "Add PostgreSQL"**
   — a Railway já injeta a variável `DATABASE_URL` automaticamente no seu
   serviço, não precisa copiar/colar nada.
4. Espere o deploy terminar e abra a aba **"Settings" → "Networking" →
   "Generate Domain"** do serviço — isso gera o link público
   (`https://algo.up.railway.app`).
5. Acesse esse link: a primeira execução roda o `seed()` automaticamente
   (mesmo comportamento do ambiente local) e imprime as credenciais
   iniciais nos **logs** do serviço (aba "Deployments" → "View Logs") —
   é lá que você vai pegar a senha do `admin` gerada em produção.

Pronto: qualquer pessoa com esse link consegue testar de qualquer rede,
sem VPN nem estar no mesmo Wi-Fi. `requirements.txt` já inclui o driver
do Postgres (`psycopg2-binary`) e `app/database.py` já lê `DATABASE_URL`
do ambiente — nenhum código muda entre local e produção.

**Depois do primeiro deploy**, cada `git push` novo faz a Railway
reimplantar automaticamente (se você conectou via GitHub).

## O que falta para virar sistema de produção (próximos passos com o Claude Code)

1. **Driver de hardware**: impressora e leitor do SK210 já integrados
   com as SDKs reais da Gertec -- ver seção "App Android nativo para os
   totens" abaixo. Falta só testar no equipamento físico (ainda não
   testado) e, se o SK315 tiver alguma diferença de API, ajustar. O SDK
   de reconhecimento facial (credenciados/mensalistas) continua
   pendente, sem resposta da Gertec até agora.
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
   a tabela de tarifa, login/papéis (incluindo operador), isolamento entre
   unidades, mensalidade configurável por unidade, revalidação de cupom no
   totem de saída, auditoria unificada, CRUD de usuários e a manutenção do
   pátio. Rodar com `python -m pytest tests/ -v` (dependências de teste em
   `requirements-dev.txt`). 142 testes no total.
7. ~~**Painel de gestão**~~ ✅ `http://localhost:8000/gestao` — unidades,
   estabelecimentos conveniados, credenciados/mensalistas, usuários,
   dashboard, conciliação financeira e auditoria unificada. Ver
   `app/rotas_gestao.py`.
8. ~~**Operação assistida e telas de totem reais**~~ ✅ login de operador
   (`/operacao`) e as telas de cada equipamento (`/totem/entrada`,
   `/totem/saida`, `/totem/validacao`) — ver seção "Páginas" acima.

## App Android nativo para os totens (`android-totem/`)

As telas de totem (`/totem/entrada`, `/totem/saida`, `/totem/validacao`)
já bloqueiam, via código, zoom por pinça, seleção de texto, o menu de
segurar-o-dedo e o "puxar pra atualizar" — mas um navegador comum nunca
consegue chamar a impressora térmica nem (dependendo do leitor) o
scanner de código de barras/QR do equipamento, só um app nativo tem
acesso a esses SDKs. `android-totem/` é um projeto Android Studio
próprio, pensado pro **Gertec Smart Kiosk SK210** (Android 13, impressora
+ leitor 1D/2D integrados) e equivalente (**SK315**):

- **`MainActivity`**: tela nativa de escolha (Entrada / Saída /
  Validação) -- é essa restrição nativa, não uma regra em JavaScript, que
  garante que o app nunca alcança `/gestao`, `/operacao`, `/pos` ou
  qualquer outra página do sistema.
- **`TotemActivity`**: `WebView` em tela cheia (sem chrome de navegador)
  carregando a URL escolhida, com `domStorageEnabled = true` (essencial
  -- os totens guardam a sessão de login por até 90 dias em
  `localStorage`) e em **modo quiosque** (`startLockTask()`, o
  equivalente automático do "Fixar app" manual do Android). Um gesto de
  5 toques no canto inferior esquerdo, em até 3s, sai do modo quiosque e
  volta pra tela de escolha -- não tem PIN nessa saída de propósito,
  porque o destino continua sendo só as 3 telas de totem, nunca uma área
  restrita.
- **`AndroidBridge`**: ponte `window.AndroidBridge` exposta ao
  JavaScript da página (`addJavascriptInterface`), com integração real
  das SDKs oficiais da Gertec (baixadas do portal de desenvolvedor deles,
  gertec.atlassian.net, a partir dos exemplos "Micro exemplo de
  impressão com WebView - GERSDK" e "Micro exemplo Scanner - SK210"):
  - **Impressora** -- `br.com.gertec.gdk.printer.*` ("GerSDK Varejo", AAR
    em `app/libs/GerSDKVarejo_1_0_3.aar`). `AndroidBridge` expõe
    `printText(texto)`, `printCode(conteúdo)` (QR/código de barras),
    `scrollPaper()` e `cutPaper()` -- as páginas de totem chamam essa
    sequência em `chamarImpressao()` no lugar de `window.print()` (com
    fallback pro `window.print()` normal se a ponte não existir, então
    as páginas continuam funcionando iguais num navegador comum/no
    simulador).
  - **Leitor** -- testado e confirmado que **não** funciona como teclado
    (HID/keyboard-wedge); precisa da SDK `br.com.gertec.easylayer.
    codescanner.CodeScanner` ("EasyLayer", AAR em
    `app/libs/EasyLayer_SK210_v219_release.aar`). `AndroidBridge` expõe
    `iniciarLeitura()`/`pararLeitura()`; cada leitura chega em
    `TotemActivity.onActivityResult` e é repassada pra página via
    `window.receberCodigoLido(texto)` (definida em `totem_saida.html` e
    `totem_validacao.html`), que preenche o campo em foco e dispara o
    mesmo tratamento de Enter que já existia pra digitação manual --
    sem duplicar lógica de validação. As telas ligam/desligam o leitor
    sozinhas ao entrar/sair (ver `mostrarPagina()` em cada página);
    `totem_entrada.html` não lê nada, só emite ticket.

### Como buildar/instalar

Precisa do [Android Studio](https://developer.android.com/studio)
(inclui JDK, SDK e `adb`) numa máquina com o equipamento conectado por
USB (com "Depuração USB" ativada nas opções de desenvolvedor do
Android). Depois:

1. `git pull` neste repositório.
2. Abrir a pasta `android-totem/` no Android Studio (se pedir pra criar o
   Gradle wrapper na primeira vez, aceitar).
3. Com o aparelho conectado, clicar em **Run**.

A URL do backend está centralizada em `android-totem/app/src/main/java/com/mypark/totem/Config.kt`
-- só precisa mudar ali se o domínio mudar. Os dois AARs da Gertec já
estão versionados em `android-totem/app/libs/` -- não são publicados em
nenhum repositório Maven público, então não tem como o Gradle baixar
sozinho se algum dia forem removidos.

**O projeto já foi compilado de ponta a ponta com sucesso** (fora deste
repositório, sem Android Studio -- JDK 17 + Android SDK cmdline-tools +
Gradle 8.7 instalados avulsos só pra validar o build) e gera um APK de
debug instalável. Três problemas reais foram encontrados e corrigidos
nesse processo, documentados aqui porque não são óbvios e podem voltar
se o SDK da Gertec for atualizado:

1. **Comentário XML com `--`**: comentários `<!-- -- -->` no meio do
   texto são inválidos por especificação do XML (só o `-->` final pode
   ter `--`). Alguns comentários usavam "--" como travessão estilístico
   -- trocados por vírgula/ponto-e-vírgula nos arquivos `.xml` (nos
   `.kt`/`.gradle` não tem esse problema, `//` não liga pra isso).
2. **Caminho do repositório com acento**: `.../Área de Trabalho/...`
   contém caractere não-ASCII, e o Android Gradle Plugin recusa compilar
   nesse caso por padrão. `android.overridePathCheck=true` em
   `gradle.properties` (sugestão do próprio erro do AGP) resolve.
3. **Classes duplicadas entre os dois AARs da Gertec**: `EasyLayer` (leitor)
   e `GerSDKVarejo` (impressora) embutem, cada um, sua própria cópia de
   bibliotecas internas de terceiros -- OpenCV (`org.opencv.*`), USB serial
   (`com.felhr.*`) e um SDK Topwise (`com.topwise.*`/`com.android.topwise.*`,
   dentro de `libs/TOPSDK_V3.6.4_20260319.jar`,
   `libs/openv-android-3.4.1.jar` e `libs/usbserial.jar`, todos dentro do
   `.aar` do GerSDKVarejo, não só no `classes.jar` principal). Usar os
   dois AARs juntos falha o build com "Duplicate class". Como nada do
   que a gente realmente usa (`Printer`, `TextFormat`, `BarcodeFormat`,
   `BarcodeType`, `CutType` -- conferido com `javap`, nenhuma dessas
   classes referencia opencv/felhr/topwise) depende desses 3 arquivos,
   `app/libs/GerSDKVarejo_1_0_3.aar` neste repositório **já está sem
   eles** (removidos do `.aar`, que é só um zip -- `NONPAYSDK_*.jar` e
   `TSG810-Printer.jar`, que não duplicam nada, continuam intactos). Se
   um dia a Gertec mandar uma versão nova do GerSDKVarejo, precisa repetir
   esse mesmo tratamento antes de substituir o arquivo (abrir o `.aar`
   como zip, conferir `libs/*.jar` com `jar tf` procurando por
   `org/opencv`, `com/felhr`, `com/topwise`/`com/android/topwise`, e
   remover os arquivos que só contêm isso).

**Compila e gera APK** (confirmado); **ainda não testado no equipamento
físico**. A integração foi escrita a partir dos exemplos oficiais da
Gertec (mesma assinatura de métodos, de propósito, pra reduzir risco de
divergir do que eles testaram), incluindo uma checagem já feita nos
manifestos dos dois AARs (`app/libs/*.aar`, que são arquivos zip -- dá
pra abrir com `unzip`): o leitor usa a câmera (`android.permission.
CAMERA`, permissão "perigosa", pedida em tempo de execução por
`TotemActivity.pedirPermissaoCameraSeNecessario()` antes da primeira
leitura) e nenhum dos dois exige nenhum passo de ativação/licença
separado de `Printer.getInstance()`/`CodeScanner.getInstance()`. Falta
confirmar na prática:

1. Se a bobina de papel está instalada antes de testar a impressão
   (senão falha por motivo trivial, não pela integração).
2. Rodar o app e conferir se a tela de escolha nativa abre sem crash.
3. **Entrada**: emitir um ticket e conferir se a impressora imprime
   algo legível. Se não imprimir nada, olhar o Logcat filtrando por
   `AndroidBridge` -- os erros de impressão são logados com `Log.e`.
4. **Saída**: apresentar um ticket já emitido pro leitor (câmera) e
   conferir se o campo preenche sozinho e a verificação roda sem
   precisar digitar nada. Na primeira vez deve aparecer o popup de
   permissão de câmera -- aceitar.
5. **Validar cupom** (Saída ou Validação): ler o QR de uma nota fiscal
   de verdade e conferir se o valor é reconhecido (a leitura precisa
   trazer a URL/conteúdo completo do QR, não só a chave de 44 dígitos).
6. Gesto de saída do quiosque: 5 toques rápidos no canto inferior
   esquerdo da tela, confirma que volta pra tela de escolha.

Qualquer erro do Logcat ou comportamento inesperado nesse teste, me
mandar que eu ajusto o código a partir disso.
