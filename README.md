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

Depois abra `http://localhost:8000/docs` — o Swagger já vem pronto e dá
para testar os quatro endpoints direto pelo navegador, sem precisar de
hardware nenhum. As regras de tolerância já são inseridas automaticamente
no banco (SQLite local, `estacionamento.db`) na primeira execução.

## Endpoints e onde cada um se encaixa no fluxo

| Endpoint | Chamado por | O que faz |
|---|---|---|
| `POST /entrada` | Totem emissor | Cria o ticket, retorna o código de barras para impressão |
| `POST /loja/validar-cupom` | Totem de autoatendimento (após ler o QR code) | Vincula a nota fiscal ao ticket, garantindo unicidade da chave |
| `GET /saida/verificar/{codigo_barras}` | Totem leitor da cancela | Calcula permanência, aplica tolerância, decide se libera |
| `POST /saida/pagamento` | Totem de pagamento | Registra pagamento quando o valor excedeu a tolerância |
| `POST /credenciados/entrada` | Totem de entrada (leitura facial) | Reconhece credenciado/mensalista pelo identificador facial e libera entrada |
| `POST /credenciados/saida` | Totem de saída (leitura facial) | Libera a saída do credenciado/mensalista reconhecido |
| `POST /gestao/credenciados` | Painel de gestão | Cadastra um credenciado ou mensalista |
| `GET /gestao/credenciados` | Painel de gestão | Lista credenciados/mensalistas |
| `PATCH /gestao/credenciados/{id}` | Painel de gestão | Edita dados / ativa / desativa |
| `POST /gestao/credenciados/{id}/renovar` | Painel de gestão | Registra pagamento de mensalidade (+30 dias) |
| `GET /gestao/relatorio/tickets` | Painel de gestão | Lista tickets por período |
| `GET /gestao/relatorio/financeiro` | Painel de gestão | Conciliação financeira por período e forma de pagamento |
| `GET /gestao/relatorio/cupons-duplicados` | Painel de gestão | Auditoria de tentativas de reuso de cupom fiscal |
| `POST /gestao/liberacao-manual` | Painel de gestão | Libera uma cancela manualmente (fluxo automático falhou) |
| `GET /gestao/relatorio/liberacoes-manuais` | Painel de gestão | Auditoria de liberações manuais |

## Liberação manual de cancela (uso excepcional)

Existe pra cobrir os casos em que o fluxo automático falha (totem travou,
ticket não foi emitido, leitor com defeito) — abre a cancela na mão, pelo
painel de gestão, sem depender de um ticket válido existir.

Duas proteções de propósito, por ser uma ação com efeito físico real:

- **Chave própria** (`API_KEY_LIBERACAO_MANUAL`), separada da chave geral
  de gestão — quem só consulta relatórios não consegue acionar isso.
- **Motivo obrigatório** e **registro de auditoria** (`app/models.py`
  `LiberacaoManual`) — toda liberação manual fica rastreada: qual cancela,
  por quê, quando, e o ticket relacionado (se houver — o vínculo é
  opcional, já que às vezes o próprio ticket é o motivo da falha).

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

- Sem cupom: 15 min de tolerância.
- Cupom de qualquer valor: 30 min.
- Cupom ≥ R$ 45: 60 min.
- Cupom ≥ R$ 90: 90 min.
- Cupom ≥ R$ 150: 360 min (6h).
- É tolerância, não gratuidade: passou do limite, cobra a permanência inteira.
- Chave de acesso da NFC-e é `UNIQUE` no banco — impede reuso do mesmo cupom.

Essas regras vivem na tabela `RegraTolerancia` (veja `app/seed.py`) —
dá para alterar valores e faixas sem mexer no código, só editando os dados.

## Painéis

- **`http://localhost:8000/`** — painel de testes dos totens: emitir ticket,
  validar cupom, verificar saída, registrar pagamento e simular o acesso
  facial de credenciados/mensalistas, tudo clicando em botões.
- **`http://localhost:8000/gestao`** — painel de gestão: cadastro de
  credenciados/mensalistas (com renovação de mensalidade), relatório de
  tickets, conciliação financeira e auditoria de cupons duplicados.

Cada painel tem sua própria chave de API (barra no topo da página) — ver
seção de autenticação abaixo.

## O que falta para virar sistema de produção (próximos passos com o Claude Code)

1. **Driver de hardware**: escrever o adapter que fala o protocolo real de
   cada equipamento (TCP/IP, webhook, SDK) e chama esses endpoints. Isso
   depende da documentação técnica que os fornecedores vão te passar.
2. ~~**Cálculo de tarifa real**~~ ✅ `services.calcular_tarifa()` já usa a
   tabela real: R$10 a 1ª hora, +R$5 por hora adicional, travando em R$35
   até 12h (diária); depois disso o ciclo reinicia.
3. **Meio de pagamento**: `/saida/pagamento` hoje só registra manualmente —
   falta integrar um gateway (PIX, cartão) de verdade.
4. ~~**Autenticação/autorização**~~ ✅ cada totem (entrada, validação, saída)
   usa sua própria chave de API, enviada no header `X-API-Key`. Ver
   `app/security.py` e as variáveis `API_KEY_*` no `.env.example`. Sem
   configurar, cada totem usa uma chave padrão de desenvolvimento (o
   servidor avisa no log até você trocar).
5. ~~**Trocar SQLite por Postgres/MySQL**~~ ✅ o código já lê `DATABASE_URL`
   do ambiente (ver `.env.example`) — sem SQLite continua sendo usado por
   padrão. Falta só **escolher onde hospedar** (Postgres é a recomendação;
   um serviço gerenciado tipo Railway/Supabase/Neon evita ter que
   administrar servidor de banco) e instalar o driver correspondente
   (`psycopg2-binary` ou `pymysql`, comentados no `requirements.txt`).
6. ~~**Testes automatizados**~~ ✅ `tests/` cobre os cenários de tolerância
   (dentro do limite, no limite exato, excedido, cupom duplicado), a
   tabela de tarifa, autenticação e o fluxo de credenciados/mensalistas.
   Rodar com `python -m pytest tests/ -v` (dependências de teste em
   `requirements-dev.txt`). 42 testes no total.
7. ~~**Painel de gestão**~~ ✅ `http://localhost:8000/gestao` — cadastro de
   credenciados/mensalistas, relatório de tickets, conciliação financeira
   e auditoria de cupons duplicados. Ver `app/rotas_gestao.py`.

Este protótipo não foi testado contra o ambiente de execução real (o
ambiente usado para criá-lo não tem acesso à internet para instalar as
dependências) — a sintaxe foi validada, mas rode os testes acima assim
que instalar as dependências, antes de seguir com a integração de hardware.
