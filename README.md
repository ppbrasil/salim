# Salim

Controle financeiro pessoal/familiar sobre **partidas dobradas** (todo lançamento soma zero), com gestão por **competência (mês)**, títulos a pagar/receber (faturas, parcelas, boletos, reembolsos), DRE, fluxo de caixa executado e futuro, orçamento e canais de entrada (web, Telegram, WhatsApp, MCP). Nome provisório.

## Produção (passo a passo)

Precisa de: um servidor com Docker (VPS pequeno basta; 1 GB de RAM) e, para HTTPS público, um domínio apontando para ele.

1. **Código no servidor:** `git clone` do seu repositório (ou copie o `salim.tar.gz` e extraia).
2. **Configuração:** `cp .env.example .env` e edite. Gere a senha e a chave de sessão:
   `docker compose run --rm salim python -m salim.passwd` (cole as duas linhas no `.env`). Sem isso o app **não sobe**.
3. **Subir com HTTPS:** aponte o DNS do `SALIM_DOMAIN` para o servidor, libere as portas 80 e 443 e rode
   `docker compose --profile https up -d --build`. O Caddy emite o certificado sozinho. Acesse `https://SEU_DOMINIO` e entre com usuário e senha.
   - *Sem domínio público (mais seguro para uso pessoal):* rode `docker compose up -d --build`, ponha `SALIM_COOKIE_SECURE=0` no `.env` e acesse por túnel (`ssh -L 8000:127.0.0.1:8000 servidor` ou Tailscale) em `http://127.0.0.1:8000`. Telegram/WhatsApp, porém, precisam de URL pública.
4. **Telegram (opcional):** crie o bot no @BotFather, preencha `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_IDS` (seu ID numérico) e `TELEGRAM_WEBHOOK_SECRET` (qualquer texto longo), suba de novo e registre o webhook:
   `curl "https://api.telegram.org/bot<TOKEN>/setWebhook" -d url=https://SEU_DOMINIO/telegram/webhook -d secret_token=<TELEGRAM_WEBHOOK_SECRET>`
5. **Backup:** o serviço `backup` grava uma cópia consistente por dia em `/data/backups` (30 últimas). Isso protege de erro, **não** de perder o servidor: copie para fora com regularidade, por exemplo, no cron do host:
   `docker compose cp backup:/data/backups ./backups-local && rclone sync ./backups-local remoto:salim`.
   Restaurar: pare o app e substitua `/data/salim.db` por um dos arquivos de backup.
6. **Atualizar:** `git pull && docker compose --profile https up -d --build` (o banco fica no volume `salim-data`).

Antes de usar para valer, faça um backup e **restaure uma vez de teste**; backup nunca restaurado não conta.

Desenvolvimento local sem senha: `SALIM_AUTH_DISABLED=1 uvicorn --factory salim.app:create_app` (nunca em servidor).

Testes: `pip install -e ".[dev]" && python -m pytest -q -W error`.

## Telas

`/ui/accounts` plano de contas · `/ui/transactions/new` novo lançamento · `/ui/payables` a pagar e a receber · `/ui/reports/dre` · `/ui/reports/cash` · `/ui/budget`.

## Configuração (variáveis de ambiente)

| Variável | Para quê |
|---|---|
| `SALIM_USER`, `SALIM_PASSWORD_HASH`, `SALIM_SECRET_KEY`, `SALIM_API_TOKEN`, `SALIM_COOKIE_SECURE` | Login. Hash e chave vêm de `python -m salim.passwd`; o token (opcional) libera scripts via `Authorization: Bearer`. Webhooks e `/health` ficam fora do login |
| `SALIM_DB_URL` | Banco (padrão `sqlite:///data/salim.db`; no container `/data`) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_IDS`, `TELEGRAM_WEBHOOK_SECRET` | Bot; só IDs listados (separados por vírgula) recebem resposta. Webhook em `POST /telegram/webhook`; o segredo é obrigatório quando há token |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_ALLOWED_NUMBERS` | WhatsApp Cloud API. Webhook em `/whatsapp/webhook`; sem `APP_SECRET` toda entrega é recusada |

Telegram: `/saldo [conta]`, `/orcamento`, `/faturas`, `/lancar <valor> <débito> <crédito> <descrição>`, `/ok`, `/cancelar`, ou texto livre ("gastei 45,90 no mercado" → proposta → `/ok`).

## MCP

```bash
docker compose run --rm -T salim python -m salim.mcp_server     # stdio (acessa o banco direto, sem passar pelo login web)
```

Ferramentas: `get_balance`, `get_statement`, `get_budget_status`, `get_upcoming_payables`, `propose_transaction` (não grava), `confirm_transaction` (idempotente por `external_ref`).

## Importação de extrato

`POST /imports/csv` (`{"account_code": "1.01.01", "csv_text": "..."}`) → fila · `POST /imports/match` casa com lançamentos existentes · `POST /imports/{id}/book` lança · `POST /imports/{id}/ignore`. Conectores bancários (Open Finance) implementam `BankConnector` em `salim/bankimport.py`.

## Mapa

`docs/MODELO.md` (modelo e decisões) · `docs/PLANO.md` · `docs/HISTORIAS.md` · `src/salim/schema.sql` (fonte única do banco; integridade nos triggers).
