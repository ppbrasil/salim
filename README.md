# Salim

Controle financeiro pessoal/familiar sobre **partidas dobradas** (todo lançamento soma zero), com gestão por **competência (mês)**, títulos a pagar/receber (faturas, parcelas, boletos, reembolsos), DRE, fluxo de caixa executado e futuro, orçamento e canais de entrada (web, Telegram, WhatsApp, MCP). Nome provisório.

## Subir

```bash
docker compose up --build        # http://localhost:8000  (dados no volume salim-data)
```

Sem Docker: `pip install -e ".[dev]"` e `SALIM_DB_URL=sqlite:///data/salim.db uvicorn --factory salim.app:create_app`.

Testes: `python -m pytest -q -W error`.

## Telas

`/ui/accounts` plano de contas · `/ui/transactions/new` novo lançamento · `/ui/payables` a pagar e a receber · `/ui/reports/dre` · `/ui/reports/cash` · `/ui/budget`.

## Configuração (variáveis de ambiente)

| Variável | Para quê |
|---|---|
| `SALIM_DB_URL` | Banco (padrão `sqlite:///data/salim.db`; no container `/data`) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_IDS`, `TELEGRAM_WEBHOOK_SECRET` | Bot; só IDs listados (separados por vírgula) recebem resposta. Webhook em `POST /telegram/webhook` |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_ALLOWED_NUMBERS` | WhatsApp Cloud API. Webhook em `/whatsapp/webhook`; sem `APP_SECRET` toda entrega é recusada |

Telegram: `/saldo [conta]`, `/orcamento`, `/faturas`, `/lancar <valor> <débito> <crédito> <descrição>`, `/ok`, `/cancelar`, ou texto livre ("gastei 45,90 no mercado" → proposta → `/ok`).

## MCP

```bash
docker compose run --rm -T salim python -m salim.mcp_server     # stdio
```

Ferramentas: `get_balance`, `get_statement`, `get_budget_status`, `get_upcoming_payables`, `propose_transaction` (não grava), `confirm_transaction` (idempotente por `external_ref`).

## Importação de extrato

`POST /imports/csv` (`{"account_code": "1.01.01", "csv_text": "..."}`) → fila · `POST /imports/match` casa com lançamentos existentes · `POST /imports/{id}/book` lança · `POST /imports/{id}/ignore`. Conectores bancários (Open Finance) implementam `BankConnector` em `salim/bankimport.py`.

## Mapa

`docs/MODELO.md` (modelo e decisões) · `docs/PLANO.md` · `docs/HISTORIAS.md` · `src/salim/schema.sql` (fonte única do banco; integridade nos triggers).
