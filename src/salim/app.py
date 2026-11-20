import hashlib
import hmac
import logging
import os
from urllib.parse import quote
from datetime import date
from pathlib import Path

from contextlib import contextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from salim.money import brl, parse_brl
from salim.auth import AuthConfig, LoginLimiter, make_session, read_session, verify_password
from salim.channels import WhatsAppChannel, WhatsAppSender
from salim.telegram import Bot, HttpSender
from salim import bankimport as imp, budget as bud, ledger, obligations as obl, reports, viz
from salim.chart import seed_chart
from salim.clock import today as clock_today
from salim.db import make_session_factory
from salim.models import Account, AccountType


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


templates.env.filters["brl"] = brl
templates.env.filters["data"] = lambda iso: f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"
templates.env.filters["mes"] = lambda iso: f"{MESES[int(iso[5:7]) - 1]}/{iso[:4]}"
templates.env.filters["mes_curto"] = viz.mes_curto
templates.env.filters["num"] = lambda c: brl(c).replace("R$ ", "")
templates.env.globals.update(line_chart=viz.line_chart, bar_chart=viz.bar_chart, legend=viz.legend, sparkline=viz.sparkline)


class EntryIn(BaseModel):
    account_code: str
    amount_cents: int
    competence: date | None = None
    obligation_id: int | None = None


class AccountIn(BaseModel):
    code: str
    name: str
    type: AccountType
    parent_code: str | None = None
    is_group: bool = False
    is_cash: bool = False
    tracks_obligations: bool = False
    is_temporary: bool = False
    closing_day: int | None = None
    due_day: int | None = None


class AccountPatch(BaseModel):
    name: str | None = None
    new_code: str | None = None
    parent_code: str | None = None


class BillIn(BaseModel):
    event_date: date
    description: str
    expense_account: str
    amount_cents: int
    due_date: date
    payable_account: str = "2.02.01"
    counterparty: str | None = None
    reference: str | None = None
    competence: date | None = None


class ItemIn(BaseModel):
    account_code: str
    amount_cents: int


class InvoiceRefIn(BaseModel):
    closing_date: date
    due_date: date


class CardPurchaseIn(BaseModel):
    card_code: str
    event_date: date
    description: str
    items: list[ItemIn]
    installments: int = 1
    competence: date | None = None
    invoices: list[InvoiceRefIn] | None = None  # (fechamento, vencimento) por parcela; padrão: regra do cartão


class SettleItemIn(BaseModel):
    obligation_id: int
    amount_cents: int | None = None


class SettleIn(BaseModel):
    event_date: date
    cash_account_code: str
    items: list[SettleItemIn]
    fees: list[ItemIn] = []
    description: str = "Pagamento"


class InstallmentsIn(BaseModel):
    event_date: date
    installments: int
    first_due_date: date
    interest_cents: int = 0


class ConsolidateIn(BaseModel):
    obligation_ids: list[int]
    event_date: date
    due_date: date
    fine_cents: int = 0
    interest_cents: int = 0
    reference: str | None = None


class ReimbursementItemIn(BaseModel):
    event_date: date
    description: str
    amount_cents: int
    expense_account: str
    competence: date | None = None
    reference: str | None = None       # só ao abrir um pedido novo
    counterparty: str | None = None
    due_date: date | None = None


class RescheduleIn(BaseModel):
    due_date: date | None = None
    planned_date: date | None = None
    clear_planned: bool = False


class ReimbursableIn(BaseModel):
    event_date: date
    description: str
    expense_account: str
    my_share_cents: int
    other_share_cents: int
    counterparty: str
    due_date: date
    payer_account_code: str


@contextmanager
def business_errors():
    try:
        yield
    except ledger.DuplicateAccountError as e:
        raise HTTPException(409, f"conta já existe: {e}")
    except ledger.AccountNotFoundError as e:
        raise HTTPException(422, f"conta inexistente: {e}")
    except (ledger.InvalidAccountError, ledger.InvalidTransactionError, obl.ObligationError, bud.BudgetError, imp.ImportError_) as e:
        raise HTTPException(422, str(e))


class BudgetIn(BaseModel):
    account_code: str
    amount_cents: int
    month: date | None = None
    profile: str = "spread"
    day_of_month: int | None = None


class ImportCsvIn(BaseModel):
    account_code: str
    csv_text: str


class BookIn(BaseModel):
    counter_account: str


class TransactionIn(BaseModel):
    event_date: date
    description: str
    entries: list[EntryIn]


def _default_factory():
    url = os.environ.get("DATABASE_URL") or os.environ.get("SALIM_DB_URL") or "sqlite:///data/salim.db"
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return make_session_factory(url)


def _env_ids() -> set[int]:
    return {int(x) for x in os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",") if x.strip()}


def _env_numbers() -> set[str]:
    return {x.strip() for x in os.environ.get("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if x.strip()}


_UNSET = object()
OPEN_PATHS = ({"/health", "/login", "/telegram/webhook", "/whatsapp/webhook"})


def _safe_next(n: str | None) -> str:
    return n if n and n.startswith("/") and not n.startswith("//") and "\\" not in n else "/"


def create_app(session_factory=None, *, auth=_UNSET, telegram_sender=None, telegram_allowed_ids=None, telegram_secret=None,
               whatsapp_sender=None, whatsapp_allowed=None, whatsapp_verify_token=None,
               whatsapp_app_secret=None, seed: bool = True) -> FastAPI:
    cfg = AuthConfig.from_env() if auth is _UNSET else auth      # falha fechada: sem senha o app não sobe
    sf = session_factory or _default_factory()
    if seed:        # no deploy serverless o plano padrão vem de `python -m salim.migrate --seed`, não da partida
        with sf() as s:
            if s.query(Account).first() is None:
                seed_chart(s)

    app = FastAPI(title="Salim")
    app.state.sf = sf

    limiter = LoginLimiter(sf)

    @app.middleware("http")
    async def exigir_login(request: Request, call_next):
        if cfg is None:
            return await call_next(request)
        usuario = read_session(cfg, request.cookies.get("salim_session", ""))
        if usuario is None and cfg.api_token:
            h = request.headers.get("Authorization", "")
            if h.startswith("Bearer ") and hmac.compare_digest(h[7:], cfg.api_token):
                usuario = "api"
        request.state.user = usuario
        if usuario is None and request.url.path not in OPEN_PATHS:
            if request.url.path == "/" or request.url.path.startswith("/ui"):
                return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)
            return JSONResponse({"detail": "não autenticado"}, status_code=401)
        return await call_next(request)

    @app.get("/login")
    def login_page(request: Request, next: str = "/"):
        return templates.TemplateResponse(request, "login.html", {"next": _safe_next(next), "erro": None})

    @app.post("/login")
    async def login(request: Request):
        form = dict((await request.form()).items())
        destino = _safe_next(form.get("next"))
        if limiter.locked():
            return templates.TemplateResponse(request, "login.html", {
                "next": destino, "erro": "Muitas tentativas. Aguarde alguns minutos."}, status_code=429)
        ok_senha = verify_password(form.get("password", ""), cfg.password_hash)      # sempre roda: tempo constante
        if not (ok_senha and hmac.compare_digest(form.get("username", ""), cfg.username)):
            limiter.failure()
            return templates.TemplateResponse(request, "login.html", {
                "next": destino, "erro": "Usuário ou senha inválidos."}, status_code=401)
        limiter.success()
        r = RedirectResponse(destino, status_code=303)
        r.set_cookie("salim_session", make_session(cfg), max_age=cfg.session_days * 86400, httponly=True,
                     samesite="lax", secure=cfg.cookie_secure)
        return r

    @app.post("/logout")
    def logout():
        r = RedirectResponse("/login", status_code=303)
        r.delete_cookie("salim_session")
        return r

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    sender = telegram_sender or (HttpSender(token) if token else (lambda chat, texto: None))
    segredo = telegram_secret if telegram_secret is not None else os.environ.get("TELEGRAM_WEBHOOK_SECRET")
    if token and not segredo:
        raise RuntimeError("TELEGRAM_BOT_TOKEN definido sem TELEGRAM_WEBHOOK_SECRET: o webhook ficaria aberto")
    bot = Bot(sf, telegram_allowed_ids if telegram_allowed_ids is not None else _env_ids())

    def _responder(replies, send, canal):
        for r in replies:
            try:
                send(r.chat_id, r.text)
            except Exception:  # resposta perdida é melhor que 500: o canal reenviaria a entrega em loop
                logging.getLogger(f"salim.{canal}").exception("falha ao enviar resposta")

    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        if segredo and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != segredo:
            raise HTTPException(403, "segredo inválido")
        _responder(bot.handle(await request.json()), sender, "telegram")
        return {"ok": True}

    wa_token, wa_phone = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_ID")
    wa_send = whatsapp_sender or (WhatsAppSender(wa_token, wa_phone) if wa_token and wa_phone else (lambda to, texto: None))
    wa_verify = whatsapp_verify_token if whatsapp_verify_token is not None else os.environ.get("WHATSAPP_VERIFY_TOKEN")
    wa_secret = whatsapp_app_secret if whatsapp_app_secret is not None else os.environ.get("WHATSAPP_APP_SECRET")
    wa_bot = Bot(sf, whatsapp_allowed if whatsapp_allowed is not None else _env_numbers(), channel=WhatsAppChannel())

    @app.get("/whatsapp/webhook")
    def whatsapp_verify(request: Request):
        q = request.query_params
        if wa_verify and q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == wa_verify:
            return PlainTextResponse(q.get("hub.challenge", ""))
        raise HTTPException(403, "verificação recusada")

    @app.post("/whatsapp/webhook")
    async def whatsapp_webhook(request: Request):
        corpo = await request.body()
        esperado = "sha256=" + hmac.new((wa_secret or "").encode(), corpo, hashlib.sha256).hexdigest()
        # sem segredo configurado, nada é aceito: assinatura é a única prova de origem
        if not wa_secret or not hmac.compare_digest(request.headers.get("X-Hub-Signature-256", ""), esperado):
            raise HTTPException(403, "assinatura inválida")
        _responder(wa_bot.handle(await request.json()), wa_send, "whatsapp")
        return {"ok": True}

    def get_session():
        with sf() as s:
            yield s

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/accounts")
    def list_accounts(session=Depends(get_session)):
        saldos = ledger.balances_all(session)
        contas = ledger.account_tree(session)
        raiz: list[dict] = []
        pilha: list[tuple[int, dict]] = []
        for depth, c in contas:
            no = {"code": c.code, "name": c.name, "type": c.type.value, "is_group": c.is_group,
                  "is_cash": c.is_cash, "tracks_obligations": c.tracks_obligations,
                  "balance_cents": saldos.get(c.id, 0), "children": []}
            while pilha and pilha[-1][0] >= depth:
                pilha.pop()
            (pilha[-1][1]["children"] if pilha else raiz).append(no)
            pilha.append((depth, no))
        return raiz

    @app.post("/transactions", status_code=201)
    def create_transaction(body: TransactionIn, session=Depends(get_session)):
        try:
            tx = ledger.post_transaction(
                session, event_date=body.event_date, description=body.description,
                entries=[ledger.Entry(e.account_code, e.amount_cents, e.competence, e.obligation_id)
                         for e in body.entries])
        except ledger.AccountNotFoundError as e:
            raise HTTPException(422, f"conta inexistente: {e}")
        except ledger.InvalidTransactionError as e:
            raise HTTPException(422, str(e))
        return {"id": tx.id}

    @app.get("/accounts/{code}/statement")
    def account_statement(code: str, session=Depends(get_session)):
        try:
            return ledger.statement(session, code)
        except ledger.AccountNotFoundError:
            raise HTTPException(404, f"conta inexistente: {code}")

    # ---------------------------------------------------------------- contas e títulos
    @app.post("/accounts", status_code=201)
    def create_account(body: AccountIn, session=Depends(get_session)):
        with business_errors():
            c = ledger.create_account(session, **body.model_dump())
        return {"id": c.id, "code": c.code, "name": c.name}

    @app.patch("/accounts/{code}")
    def patch_account(code: str, body: AccountPatch, session=Depends(get_session)):
        try:
            ledger.get_account(session, code)
        except ledger.AccountNotFoundError:
            raise HTTPException(404, f"conta inexistente: {code}")
        with business_errors():
            c = ledger.update_account(session, code, **body.model_dump())
        return {"id": c.id, "code": c.code, "name": c.name}

    @app.get("/obligations")
    def list_obligations(today: date | None = None, status: str | None = None, include_settled: bool = False,
                         session=Depends(get_session)):
        return obl.list_obligations(session, today or clock_today(), status=status, include_settled=include_settled)

    @app.post("/obligations/bills", status_code=201)
    def create_bill(body: BillIn, session=Depends(get_session)):
        with business_errors():
            o = obl.register_bill(session, **body.model_dump())
            return obl.get_obligation(session, o.id, clock_today())

    @app.post("/card-purchases", status_code=201)
    def card_purchase(body: CardPurchaseIn, session=Depends(get_session)):
        with business_errors():
            faturas = obl.register_card_purchase(
                session, card_code=body.card_code, event_date=body.event_date, description=body.description,
                items=[(i.account_code, i.amount_cents) for i in body.items], installments=body.installments,
                competence=body.competence,
                invoices=None if body.invoices is None else [(i.closing_date, i.due_date) for i in body.invoices])
            return [obl.get_obligation(session, f.id, clock_today()) for f in faturas]

    @app.post("/obligations/settle", status_code=201)
    def settle(body: SettleIn, session=Depends(get_session)):
        with business_errors():
            tx = obl.settle_obligations(
                session, event_date=body.event_date, cash_account_code=body.cash_account_code,
                items=[(i.obligation_id, i.amount_cents) for i in body.items],
                fees=[(f.account_code, f.amount_cents) for f in body.fees], description=body.description)
        return {"id": tx.id}

    @app.post("/obligations/consolidate", status_code=201)
    def consolidate(body: ConsolidateIn, session=Depends(get_session)):
        with business_errors():
            novo = obl.consolidate_obligations(session, **body.model_dump())
            return obl.get_obligation(session, novo.id, clock_today())

    @app.post("/obligations/{obligation_id}/installments", status_code=201)
    def installments(obligation_id: int, body: InstallmentsIn, session=Depends(get_session)):
        with business_errors():
            parcelas = obl.installment_obligation(session, obligation_id, **body.model_dump())
            return [obl.get_obligation(session, p.id, clock_today()) for p in parcelas]

    @app.post("/obligations/{obligation_id}/reschedule")
    def reschedule(obligation_id: int, body: RescheduleIn, session=Depends(get_session)):
        with business_errors():
            obl.reschedule_obligation(session, obligation_id, **body.model_dump())
            return obl.get_obligation(session, obligation_id, clock_today())

    @app.post("/reimbursable-expenses", status_code=201)
    def reimbursable(body: ReimbursableIn, session=Depends(get_session)):
        with business_errors():
            o = obl.register_reimbursable_expense(session, **body.model_dump())
            return obl.get_obligation(session, o.id, clock_today())

    # ---------------------------------------------------------------- importação
    def _item(i):
        return {**vars(i), "date": i.date.isoformat()}

    @app.post("/reimbursements", status_code=201)
    def new_reimbursement(body: ReimbursementItemIn, session=Depends(get_session)):
        with business_errors():
            o = obl.add_reimbursement_item(session, **body.model_dump())
            return obl.get_obligation(session, o.id, clock_today())

    @app.post("/reimbursements/{obligation_id}/items", status_code=201)
    def add_reimbursement_item(obligation_id: int, body: ReimbursementItemIn, session=Depends(get_session)):
        dados = body.model_dump(exclude={"reference", "counterparty", "due_date"})
        with business_errors():
            o = obl.add_reimbursement_item(session, obligation_id=obligation_id, **dados)
            return obl.get_obligation(session, o.id, clock_today())

    @app.post("/imports/csv", status_code=201)
    def import_csv(body: ImportCsvIn, session=Depends(get_session)):
        with business_errors():
            r = imp.import_csv(session, body.account_code, body.csv_text)
        return {"created": r.created, "skipped": r.skipped, "errors": [vars(e) for e in r.errors]}

    @app.get("/imports")
    def list_imports(status: str | None = None, session=Depends(get_session)):
        return [_item(i) for i in imp.list_items(session, status)]

    @app.post("/imports/match")
    def match_imports(session=Depends(get_session)):
        return {"matched": imp.match_items(session)}

    @app.post("/imports/{item_id}/book", status_code=201)
    def book_import(item_id: int, body: BookIn, session=Depends(get_session)):
        with business_errors():
            return {"transaction_id": imp.book_item(session, item_id, body.counter_account)}

    @app.post("/imports/{item_id}/ignore")
    def ignore_import(item_id: int, session=Depends(get_session)):
        with business_errors():
            imp.ignore_item(session, item_id)
        return {"ok": True}

    # ---------------------------------------------------------------- relatórios e orçamento
    @app.get("/reports/dre")
    def api_dre(start: date, end: date | None = None, session=Depends(get_session)):
        r = reports.dre(session, start, end)
        return {"start": r.start, "end": r.end, "income_cents": r.income_cents, "expense_cents": r.expense_cents,
                "result_cents": r.result_cents, "lines": [vars(l) for l in r.lines]}

    @app.get("/reports/dre-monthly")
    def api_dre_monthly(start: date, end: date, session=Depends(get_session)):
        m = reports.dre_monthly(session, start, end)
        return {"months": m.months, "income": m.income, "expense": m.expense, "result": m.result,
                "rows": [{**vars(r), "total_cents": r.total_cents} for r in m.rows]}

    @app.get("/reports/cash")
    def api_cash(start: date, end: date, session=Depends(get_session)):
        return [{**vars(m), "net_cents": m.net_cents} for m in reports.cash_executed(session, start, end)]

    @app.get("/reports/cash-future")
    def api_cash_future(today: date | None = None, months: int = 6, session=Depends(get_session)):
        return [{**vars(m), "net_cents": m.net_cents} for m in reports.cash_future(session, today or clock_today(), months)]

    @app.put("/budget")
    def api_set_budget(body: BudgetIn, session=Depends(get_session)):
        with business_errors():
            b = bud.set_budget(session, body.account_code, body.amount_cents, month=body.month,
                               profile=body.profile, day_of_month=body.day_of_month)
        return {"id": b.id, "amount_cents": b.amount_cents, "profile": b.profile}

    @app.get("/budget")
    def api_budget(month: date | None = None, today: date | None = None, session=Depends(get_session)):
        hoje = today or clock_today()
        return [vars(l) for l in bud.budget_vs_actual(session, month or hoje, hoje)]

    # ---------------------------------------------------------------- telas
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/ui/accounts")

    @app.get("/ui/accounts")
    def ui_accounts(request: Request, session=Depends(get_session)):
        saldos = ledger.balances_all(session)
        rows = [(d, c, saldos.get(c.id, 0)) for d, c in ledger.account_tree(session)]
        return templates.TemplateResponse(request, "accounts.html", {"rows": rows})

    @app.get("/ui/accounts/{code}")
    def ui_statement(code: str, request: Request, session=Depends(get_session)):
        try:
            conta = ledger.get_account(session, code)
        except ledger.AccountNotFoundError:
            raise HTTPException(404, f"conta inexistente: {code}")
        return templates.TemplateResponse(request, "statement.html",
                                          {"conta": conta, "linhas": ledger.statement(session, code)})

    def _titulos_page(request, session, direction, hoje, erro=None, status=200):
        todas = [v for v in obl.list_obligations(session, hoje) if v.direction == direction]
        itens = obl.obligation_items(session, [v.id for v in todas])
        caixas = [c for _, c in ledger.account_tree(session) if c.is_cash and not c.is_group]
        aberto = [v for v in todas if v.balance_cents > 0]
        ctx = {"titulos": todas, "itens": itens, "caixas": caixas, "hoje": hoje, "erro": erro,
               "total": sum(v.balance_cents for v in aberto),
               "atrasado": sum(v.balance_cents for v in aberto if v.status == "atrasada"),
               "prox7": sum(v.balance_cents for v in aberto if v.status == "a_vencer" and (v.due_date - hoje).days <= 7)}
        pagina = "payables.html" if direction == "pagar" else "receivables.html"
        return templates.TemplateResponse(request, pagina, ctx, status_code=status)

    @app.get("/ui/payables")
    def ui_payables(request: Request, today: date | None = None, session=Depends(get_session)):
        return _titulos_page(request, session, "pagar", today or clock_today())

    @app.get("/ui/receivables")
    def ui_receivables(request: Request, today: date | None = None, session=Depends(get_session)):
        return _titulos_page(request, session, "receber", today or clock_today())

    @app.post("/ui/obligations/{obligation_id}/settle")
    async def ui_settle(obligation_id: int, request: Request, session=Depends(get_session)):
        form = await request.form()
        volta = form.get("back") if form.get("back") in ("/ui/payables", "/ui/receivables") else "/ui/payables"
        direction = "pagar" if volta == "/ui/payables" else "receber"
        try:
            dia = date.fromisoformat(form.get("event_date", ""))
            valor = parse_brl(form["amount"]) if form.get("amount", "").strip() else None
            with business_errors():
                obl.settle_obligations(
                    session, event_date=dia, items=[(obligation_id, valor)], cash_account_code=form.get("cash_account_code", ""),
                    description="Pagamento" if direction == "pagar" else "Recebimento")
        except ValueError:
            return _titulos_page(request, session, direction, clock_today(), "data ou valor inválido", 422)
        except HTTPException as e:
            return _titulos_page(request, session, direction, clock_today(), e.detail, 422)
        return RedirectResponse(volta, status_code=303)

    def _mes(v: str | None) -> date | None:
        """Aceita 'AAAA-MM' (campo month do HTML) ou uma data completa."""
        if not v:
            return None
        try:
            return ledger.month_start(date.fromisoformat(v if len(v) > 7 else v + "-01"))
        except ValueError:
            raise HTTPException(422, f"mês inválido: {v}")

    def _janela(session, start, end, hoje, max_meses=12):
        """Período padrão: do primeiro mês com movimento até o mês corrente, no máximo `max_meses` meses."""
        atual = ledger.month_start(hoje)
        ultimo = reports.last_activity_month(session)
        fim = _mes(end) or (min(atual, ultimo) if ultimo else atual)   # mês corrente ainda vazio não entra na média
        if _mes(start):
            return _mes(start), fim
        primeiro = reports.first_activity_month(session) or fim
        y, m = reports._shift(fim.year, fim.month, -(max_meses - 1))
        return max(primeiro, date(y, m, 1)), fim

    @app.get("/ui/reports/dre")
    def ui_dre(request: Request, start: str | None = None, end: str | None = None, today: date | None = None,
               session=Depends(get_session)):
        hoje = today or clock_today()
        if start and not end:       # só o início informado: um mês
            ini = fim = _mes(start)
        else:
            ini, fim = _janela(session, start, end, hoje)
        if fim < ini:
            ini, fim = fim, ini
        m = reports.dre_monthly(session, ini, fim)
        n = len(m.months)
        grupos = [r for r in m.rows if r.type == "expense" and r.depth == 1]
        top = sorted(grupos, key=lambda r: -r.total_cents)[:7]
        top_codes = sorted(g.code for g in top)
        cor = {c: i + 1 for i, c in enumerate(top_codes)}
        empilhado = [(g.name, cor[g.code], g.cents) for g in sorted(top, key=lambda r: r.code)]
        resto = [sum(g.cents[i] for g in grupos if g.code not in cor) for i in range(n)]
        if any(resto):
            empilhado.append(("Outros", 9, resto))
        return templates.TemplateResponse(request, "dre.html", {
            "m": m, "n": n, "ini": ini, "fim": fim,
            "rec_desp": [("Receitas", 1, m.income), ("Despesas", 2, m.expense)], "empilhado": empilhado,
            "resultado": m.result, "tot_rec": sum(m.income), "tot_desp": sum(m.expense)})

    @app.get("/ui/reports/cash")
    def ui_cash(request: Request, start: str | None = None, end: str | None = None, today: date | None = None,
                session=Depends(get_session)):
        hoje = today or clock_today()
        atual = ledger.month_start(hoje)
        ini, fim = _mes(start), _mes(end) or atual
        if ini is None:
            primeiro = reports.first_cash_month(session) or atual
            y, m = reports._shift(fim.year, fim.month, -11)
            ini = max(primeiro, date(y, m, 1))
        if fim < ini:
            ini, fim = fim, ini
        futuros = 3 if (not end or fim >= atual) else 0
        c = reports.cash_monthly(session, ini, fim, hoje, future_months=futuros)
        meses = [r.month for r in c.months]
        primeiro_futuro = next((i for i, r in enumerate(c.months) if r.is_future), None)
        corrente = next((r for r in c.months if r.is_current), None)
        reais = [r for r in c.months if not r.is_future]
        return templates.TemplateResponse(request, "cash.html", {
            "c": c, "n": len(meses), "ini": ini, "fim": fim, "hoje": hoje,
            "reais_meses": [r.month for r in reais],
            "entradas_saidas": [("Entradas", 1, [r.inflow_cents for r in reais]), ("Saídas", 2, [r.outflow_cents for r in reais])],
            "saldos": [r.closing_cents for r in c.months], "primeiro_futuro": primeiro_futuro,
            "saldo_atual": (corrente or (reais[-1] if reais else None)),
            "tot_in": sum(r.inflow_cents for r in reais), "tot_out": sum(r.outflow_cents for r in reais),
            "tem_orcamento": any(r.budget_net_cents is not None for r in c.months)})

    @app.get("/reports/cash-monthly")
    def api_cash_monthly(start: date, end: date, today: date | None = None, future_months: int = 3,
                         session=Depends(get_session)):
        c = reports.cash_monthly(session, start, end, today or clock_today(), future_months)
        return [{**vars(r), "net_cents": r.net_cents} for r in c.months]

    def _budget_page(request, session, month, hoje, form=None, erro=None, status=200):
        contas = [c for _, c in ledger.account_tree(session) if c.type in (AccountType.EXPENSE, AccountType.INCOME)]
        return templates.TemplateResponse(request, "budget.html", {
            "linhas": bud.budget_vs_actual(session, month, hoje), "month": ledger.month_start(month), "contas": contas,
            "form": form or {}, "erro": erro}, status_code=status)

    @app.get("/ui/budget")
    def ui_budget(request: Request, month: date | None = None, today: date | None = None, session=Depends(get_session)):
        hoje = today or clock_today()
        return _budget_page(request, session, month or hoje, hoje)

    @app.post("/ui/budget")
    async def ui_set_budget(request: Request, session=Depends(get_session)):
        form = dict((await request.form()).items())
        try:
            try:
                valor = parse_brl(form.get("amount", ""))
            except ValueError:
                raise bud.BudgetError("valor inválido")
            dia = int(form["day_of_month"]) if form.get("day_of_month") else None
            mes = date.fromisoformat(form["month"]) if form.get("month") else None
            bud.set_budget(session, form.get("account_code", "").strip(), valor, month=mes,
                           profile=form.get("profile", "spread"), day_of_month=dia)
        except bud.BudgetError as e:
            return _budget_page(request, session, clock_today(), clock_today(), form, str(e), 422)
        return RedirectResponse("/ui/budget", status_code=303)

    def _form_page(request, session, form, erro=None, status=200):
        contas = [c for _, c in ledger.account_tree(session) if not c.is_group]
        return templates.TemplateResponse(request, "transaction_form.html",
                                          {"form": form, "erro": erro, "contas": contas}, status_code=status)

    @app.get("/ui/transactions/new")
    def ui_new_transaction(request: Request, session=Depends(get_session)):
        return _form_page(request, session, {"date": clock_today().isoformat()})

    @app.post("/ui/transactions")
    async def ui_create_transaction(request: Request, session=Depends(get_session)):
        form = dict((await request.form()).items())
        try:
            entries = []
            for i in range(1, 5):
                acc = form.get(f"acc_{i}", "").strip()
                deb, cred = form.get(f"deb_{i}", "").strip(), form.get(f"cred_{i}", "").strip()
                if not acc and not deb and not cred:
                    continue
                try:
                    valor = (parse_brl(deb) if deb else 0) - (parse_brl(cred) if cred else 0)
                except ValueError:
                    raise ledger.InvalidTransactionError(f"linha {i}: valor inválido")
                entries.append(ledger.Entry(acc, valor))
            ledger.post_transaction(session, event_date=date.fromisoformat(form["date"]),
                                    description=form.get("description", ""), entries=entries)
        except ledger.AccountNotFoundError as e:
            return _form_page(request, session, form, f"conta inexistente: {e}", 422)
        except (ledger.InvalidTransactionError, ValueError, KeyError) as e:
            return _form_page(request, session, form, str(e), 422)
        return RedirectResponse("/ui/accounts", status_code=303)

    return app
