# Salim → Vercel + Neon (Postgres) + GitHub Actions

Decisão (19/11/2026): sair de "VM + SQLite" para **Vercel Hobby (app) + Neon Free (Postgres) + GitHub Actions (backup)**, tudo no plano grátis.
Este documento mapeia, no código real, o que precisa mudar. Regra de trabalho mantida: story pequena, teste primeiro, verde antes da próxima.

## 1. Arquitetura-alvo

| Peça | Hoje | Alvo |
|---|---|---|
| App | uvicorn em container, 1 processo | FastAPI na Vercel (função serverless, stateless) |
| Banco | SQLite em arquivo (`/data/salim.db`) | Postgres 17 no Neon (`DATABASE_URL`) |
| Estado do bot (proposta pendente, dedupe) | memória do processo | tabelas no banco |
| Trava de login | memória do processo | tabela no banco |
| Schema | `schema.sql` aplicado na partida se o banco é novo | migrações numeradas rodadas por CLI/CI, nunca na partida do app |
| Backup | API de backup do SQLite, a cada 24 h | `pg_dump` em GitHub Actions, criptografado, copiado para fora |
| HTTPS | Caddy | Vercel (URL `*.vercel.app`) |
| MCP | stdio local | continua stdio local, apontando para o mesmo Neon (`DATABASE_URL`) |
| Local | `docker compose` (app) | `docker compose` (app + Postgres 17) |

## 2. O que muda no código (achados do mapeamento)

**Schema (`schema.sql` → Postgres)**
- `PRAGMA`, `INTEGER PRIMARY KEY`, `RAISE(ABORT)` e triggers sem função não existem em PG: viram `GENERATED ... AS IDENTITY` e funções plpgsql com `RAISE EXCEPTION ... USING ERRCODE = 'integrity_constraint_violation'` (assim o SQLAlchemy continua levantando `IntegrityError`, que 4 testes esperam).
- **Tipos precisam ficar iguais ao que o ORM espera.** Os modelos declaram `Date` e `Boolean`, mas as colunas SQLite são TEXT e INTEGER. Em PG isso quebra (`text = date`, `integer` recebendo `boolean`). Decisão: colunas reais `DATE` e `BOOLEAN`. Consequências: `is_cash = 1` → `is_cash`; `substr(event_date,1,7)` → `to_char(event_date,'YYYY-MM')`; `date(x,'start of month')` → `date_trunc('month', x)::date`; comparações com `.isoformat()` em `reports.py` viram datas.
- **`SUM` de BIGINT devolve `numeric` (Decimal) em PG.** Dinheiro vira `BIGINT` e toda soma leva `CAST(... AS BIGINT)` (views e SQL cru de `reports.py`), senão aparece `Decimal` no JSON e nas telas.
- **`GROUP BY` mais estrito.** `v_dre` e `reports.dre` selecionam colunas fora do `GROUP BY` (a.type, a.name): o SQLite aceita, o PG recusa. Corrigir no SQL.
- **Ordenação de códigos de conta** (`ORDER BY code`): PG usa a collation do banco, que pode ignorar pontuação. Fixar `COLLATE "C"` nas colunas de código para manter a ordem lexicográfica de hoje.
- Índice único com `COALESCE(month,'default')` vira índice sobre expressão (sintaxe PG com parênteses extras).
- `lower() LIKE` em `nlentry.suggest_account`: o `lower` do PG trata acentos, o do SQLite só ASCII. Esperado: sugestão igual ou melhor; um teste pode precisar ajuste.

**Banco e partida (`db.py`, `app.py`)**
- `db.py` usa `sqlite_master`, `executescript`, `PRAGMA foreign_keys` e `StaticPool`: ramo SQLite fica isolado; PG ganha caminho próprio.
- `create_app` aplica schema e semeia o plano de contas na partida. Em serverless cada cold start repetiria isso (e duas instâncias podem correr juntas). Passa a ser `python -m salim.migrate` (migrações numeradas + tabela `schema_migrations` + seed idempotente), rodado por você/CI no deploy. Isso também fecha o risco "sem versionamento de schema" do plano anterior; sem Alembic, porque o schema é SQL puro.
- Engine para serverless: `NullPool` (cada invocação abre e fecha), conexão pelo endpoint **pooler** do Neon, `sslmode=require`, timeout de conexão e uma tentativa extra no primeiro acesso (o banco dorme após 5 min e acorda em cerca de 0,5 s). `prepare_threshold=None` por segurança com PgBouncer. **A verificar na M7**: se o pooler atual do Neon aceita prepared statements.

**Estado que hoje vive na memória do processo (quebra em serverless)**
- `telegram.Bot.pending` (proposta aguardando "sim"): vira tabela `bot_pending(channel, chat_id, payload, created_at)` com expiração.
- `telegram.Bot.seen` (dedupe de `update_id`): vira `bot_seen(channel, msg_id)` com `INSERT ... ON CONFLICT DO NOTHING`, que é atômico, e limpeza por idade. O WhatsApp usa a mesma classe.
- `auth.LoginLimiter` (5 erros → trava 15 min): contador global vira tabela `login_attempts`; em memória cada instância teria o seu e a trava não valeria nada.
- Sessão por cookie assinado (HMAC) e token Bearer já são sem estado: nada a mudar.

**Fuso horário (bug que só aparece em produção)**
- ~15 usos de `date.today()` (app, Telegram, MCP). A Vercel roda em UTC: depois das 21h em Brasília o "hoje" vira o dia seguinte e o lançamento cai na competência errada na virada do mês. Criar `salim.clock.today()` com `America/Sao_Paulo` (env `SALIM_TZ`) e trocar todos os usos.

**Empacotamento Vercel**
- Ponto de entrada com `app = create_app()` no módulo; FastAPI é detectado sem configuração e o Hobby aceita Python 3.12+. O sistema de arquivos é somente leitura (só `/tmp` grava): hoje só o SQLite grava, então some junto.
- Templates Jinja e `.sql` de migração precisam ir no pacote da função (`includeFiles` no `vercel.json`). **A verificar na M8.**
- `/telegram/webhook` e `/whatsapp/webhook` precisam estar acessíveis sem a proteção de deploy da Vercel. **A verificar na M8.**
- Hobby é **uso pessoal, não comercial**: ok para finanças da família.

**Backup (`backup.py` SQLite → GitHub Actions)**
- `pg_dump -Fc` agendado, criptografado (age) antes de sair do job, enviado para fora do GitHub; restauração testada em um Postgres limpo. Destino a decidir (Drive ou Backblaze B2, 10 GB grátis).
- **A confirmar na M9:** workflows agendados em repositório público são desativados após inatividade. Por isso o repositório deve ser **privado**.
- O dump é dado financeiro: sem log, só em artefato criptografado ou destino externo.

## 3. Rodar local antes de publicar

`docker compose --profile pg up -d db` sobe o **Postgres 17** (versão major atual do Neon, a confirmar no painel). Neste ambiente de desenvolvimento sem Docker o teste local usa o Postgres 16 do sistema; a CI usa a 17. Os 246 testes rodam contra o Postgres (`SALIM_TEST_DB_URL`): o banco é criado uma vez e cada teste limpa as tabelas com `TRUNCATE ... RESTART IDENTITY CASCADE` (TRUNCATE não dispara os triggers de imutabilidade). Durante a migração a suíte roda nos **dois** bancos; no corte, SQLite sai.

## 4. Stories (cada uma toca no máximo 1–2 arquivos de produção; teste primeiro)

| # | Story | Entrega verificável |
|---|---|---|
| M0 ✅ | Postgres de teste: serviço `db` (17) no compose, serviço na CI, driver `psycopg`, teste de conexão com trava `*_test` | 3 testes verdes no PG local (16) e na CI (17); sem a variável, são pulados |
| M1 ✅ | `schema_pg.sql` (tipos reais, identity, triggers plpgsql, views corrigidas) + `db.py` com caminho PG + `conftest` parametrizado por `SALIM_TEST_DB_URL` (TRUNCATE entre testes) | schema carrega no PG; imutabilidade e integridade já passam; suíte no PG: **197 verdes, 52 vermelhas** (lista abaixo) |
| M2 ✅ | Casts e SQL cru em `reports.py` e `nlentry.py` (SUM→BIGINT, GROUP BY, datas) | testes de DRE, caixa, orçamento verdes no PG (249 verdes) |
| M3 ✅ | `salim.migrate` + `schema_migrations` + seed fora da partida | `create_app` não escreve no banco; migrate idempotente |
| M4 ✅ | Estado do bot em tabelas (`bot_pending`, `bot_seen`) | testes do Telegram/WhatsApp verdes, reinício do processo não perde proposta |
| M5 ✅ | `LoginLimiter` em tabela | trava persiste entre instâncias (teste com duas instâncias) |
| M6 | `salim.clock.today()` em America/Sao_Paulo | teste às 23h30 BRT devolve o dia local, não o UTC |
| M7 | Engine serverless (NullPool, pooler, retry de cold start, `DATABASE_URL`) | teste de conexão contra Neon real (manual, uma vez) |
| M8 | Entrada Vercel + `vercel.json` + variáveis + `setWebhook` do Telegram | `/health` e login em HTTPS na URL da Vercel; `/saldo` no Telegram |
| M9 | Workflow de backup (`pg_dump` + criptografia + envio) + script de restauração | restauração feita em um Postgres limpo, conferindo o somatório do razão |
| M10 | Corte: remover ramo SQLite, `backup.py` antigo, Caddy; docs e README | suíte só em PG; compose vira "dev local" |

## 4b. Lista vermelha da M1 (suíte no Postgres: 197 verdes, 52 falhas) — ✅ zerada na M2 (249 verdes)

| Causa | Falhas | Onde | Story |
|---|---|---|---|
| `GROUP BY` incompleto na consulta de títulos com saldo (`accounts.id` fora do agrupamento) | ~40 | `obligations.py` | M2 |
| `is_cash = 1` em SQL cru (boolean = integer) | 5 | `reports.py` | M2 |
| `GROUP BY` incompleto no DRE (`a.name`) | 3 | `reports.py` | M2 |
| Tradução de erro depende da mensagem do SQLite ("UNIQUE constraint failed") | ~2 | `ledger.py`/`app.py` (código duplicado vira 422 em vez de 409) | M2 |
| Soma devolve `numeric` (Decimal): JSON sai como texto | ~2 | queries com `func.sum` sobre BIGINT | M2 |

Testes que dependem do SQLite por natureza (backup pela API do SQLite, `test_db.py`) seguem só em SQLite até o corte (M10).

## 5. Riscos e o que não será resolvido aqui

- Três planos grátis (Vercel, Neon, GitHub): Postgres padrão mantém a saída aberta e o backup externo cobre o risco de plano.
- Limite de 1 GB no Neon grátis: ao estourar, escritas falham (não há cobrança). Para um ledger pessoal, anos de folga; monitorar.
- Soma do lançamento = 0 segue validada no serviço. PG permite constraint trigger diferida; fica como melhoria depois do corte, não como parte dele.
- Fora do escopo: tela de importação, MCP por HTTP, WhatsApp/Telegram contra as APIs reais (M8 testa o Telegram real).
