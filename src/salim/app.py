import os
from datetime import date
from pathlib import Path

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from salim import budget as bud, ledger, obligations as obl, reports
from salim.chart import seed_chart
from salim.db import make_session_factory
from salim.models import Account, AccountType


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def brl(cents: int) -> str:
    texto = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}R$ {texto}"


def parse_brl(texto: str) -> int:
    """'3.000,00' -> 300000. Levanta ValueError se não for número."""
    limpo = texto.strip().replace(".", "").replace(",", ".")
    try:
        return int((Decimal(limpo) * 100).to_integral_value())
    except InvalidOperation:
        raise ValueError(texto)


templates.env.filters["brl"] = brl
templates.env.filters["data"] = lambda iso: f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"
templates.env.filters["mes"] = lambda iso: f"{MESES[int(iso[5:7]) - 1]}/{iso[:4]}"


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


class CardPurchaseIn(BaseModel):
    card_code: str
    event_date: date
    description: str
    items: list[ItemIn]
    installments: int = 1
    competence: date | None = None


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
    except (ledger.InvalidAccountError, ledger.InvalidTransactionError, obl.ObligationError, bud.BudgetError) as e:
        raise HTTPException(422, str(e))


class BudgetIn(BaseModel):
    account_code: str
    amount_cents: int
    month: date | None = None
    profile: str = "spread"
    day_of_month: int | None = None


class TransactionIn(BaseModel):
    event_date: date
    description: str
    entries: list[EntryIn]


def _default_factory():
    url = os.environ.get("SALIM_DB_URL", "sqlite:///data/salim.db")
    if url.startswith("sqlite:///") and ":memory:" not in url:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return make_session_factory(url)


def create_app(session_factory=None) -> FastAPI:
    sf = session_factory or _default_factory()
    with sf() as s:
        if s.query(Account).first() is None:
            seed_chart(s)

    app = FastAPI(title="Salim")
    app.state.sf = sf

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

    @app.get("/obligations")
    def list_obligations(today: date | None = None, status: str | None = None, include_settled: bool = False,
                         session=Depends(get_session)):
        return obl.list_obligations(session, today or date.today(), status=status, include_settled=include_settled)

    @app.post("/obligations/bills", status_code=201)
    def create_bill(body: BillIn, session=Depends(get_session)):
        with business_errors():
            o = obl.register_bill(session, **body.model_dump())
            return obl.get_obligation(session, o.id, date.today())

    @app.post("/card-purchases", status_code=201)
    def card_purchase(body: CardPurchaseIn, session=Depends(get_session)):
        with business_errors():
            faturas = obl.register_card_purchase(
                session, card_code=body.card_code, event_date=body.event_date, description=body.description,
                items=[(i.account_code, i.amount_cents) for i in body.items], installments=body.installments,
                competence=body.competence)
            return [obl.get_obligation(session, f.id, date.today()) for f in faturas]

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
            return obl.get_obligation(session, novo.id, date.today())

    @app.post("/obligations/{obligation_id}/installments", status_code=201)
    def installments(obligation_id: int, body: InstallmentsIn, session=Depends(get_session)):
        with business_errors():
            parcelas = obl.installment_obligation(session, obligation_id, **body.model_dump())
            return [obl.get_obligation(session, p.id, date.today()) for p in parcelas]

    @app.post("/obligations/{obligation_id}/reschedule")
    def reschedule(obligation_id: int, body: RescheduleIn, session=Depends(get_session)):
        with business_errors():
            obl.reschedule_obligation(session, obligation_id, **body.model_dump())
            return obl.get_obligation(session, obligation_id, date.today())

    @app.post("/reimbursable-expenses", status_code=201)
    def reimbursable(body: ReimbursableIn, session=Depends(get_session)):
        with business_errors():
            o = obl.register_reimbursable_expense(session, **body.model_dump())
            return obl.get_obligation(session, o.id, date.today())

    # ---------------------------------------------------------------- relatórios e orçamento
    @app.get("/reports/dre")
    def api_dre(start: date, end: date | None = None, session=Depends(get_session)):
        r = reports.dre(session, start, end)
        return {"start": r.start, "end": r.end, "income_cents": r.income_cents, "expense_cents": r.expense_cents,
                "result_cents": r.result_cents, "lines": [vars(l) for l in r.lines]}

    @app.get("/reports/cash")
    def api_cash(start: date, end: date, session=Depends(get_session)):
        return [{**vars(m), "net_cents": m.net_cents} for m in reports.cash_executed(session, start, end)]

    @app.get("/reports/cash-future")
    def api_cash_future(today: date | None = None, months: int = 6, session=Depends(get_session)):
        return [{**vars(m), "net_cents": m.net_cents} for m in reports.cash_future(session, today or date.today(), months)]

    @app.put("/budget")
    def api_set_budget(body: BudgetIn, session=Depends(get_session)):
        with business_errors():
            b = bud.set_budget(session, body.account_code, body.amount_cents, month=body.month,
                               profile=body.profile, day_of_month=body.day_of_month)
        return {"id": b.id, "amount_cents": b.amount_cents, "profile": b.profile}

    @app.get("/budget")
    def api_budget(month: date | None = None, today: date | None = None, session=Depends(get_session)):
        hoje = today or date.today()
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

    @app.get("/ui/payables")
    def ui_payables(request: Request, today: date | None = None, session=Depends(get_session)):
        hoje = today or date.today()
        todas = obl.list_obligations(session, hoje)
        pagar = [v for v in todas if v.direction == "pagar"]
        receber = [v for v in todas if v.direction == "receber"]
        return templates.TemplateResponse(request, "payables.html", {
            "pagar": pagar, "receber": receber, "hoje": hoje,
            "total_pagar": sum(v.balance_cents for v in pagar if v.balance_cents > 0),
            "total_receber": sum(v.balance_cents for v in receber if v.balance_cents > 0)})

    @app.get("/ui/reports/dre")
    def ui_dre(request: Request, start: date | None = None, end: date | None = None, session=Depends(get_session)):
        inicio = start or ledger.month_start(date.today())
        return templates.TemplateResponse(request, "dre.html", {"r": reports.dre(session, inicio, end)})

    @app.get("/ui/reports/cash")
    def ui_cash(request: Request, today: date | None = None, session=Depends(get_session)):
        hoje = today or date.today()
        inicio = ledger.month_start(hoje)
        passado = reports.cash_executed(session, date(inicio.year - (inicio.month <= 5), (inicio.month - 6) % 12 + 1, 1), inicio)
        return templates.TemplateResponse(request, "cash.html", {
            "executado": passado, "projetado": reports.cash_future(session, hoje, 6), "hoje": hoje})

    def _budget_page(request, session, month, hoje, form=None, erro=None, status=200):
        contas = [c for _, c in ledger.account_tree(session) if c.type in (AccountType.EXPENSE, AccountType.INCOME)]
        return templates.TemplateResponse(request, "budget.html", {
            "linhas": bud.budget_vs_actual(session, month, hoje), "month": ledger.month_start(month), "contas": contas,
            "form": form or {}, "erro": erro}, status_code=status)

    @app.get("/ui/budget")
    def ui_budget(request: Request, month: date | None = None, today: date | None = None, session=Depends(get_session)):
        hoje = today or date.today()
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
            return _budget_page(request, session, date.today(), date.today(), form, str(e), 422)
        return RedirectResponse("/ui/budget", status_code=303)

    def _form_page(request, session, form, erro=None, status=200):
        contas = [c for _, c in ledger.account_tree(session) if not c.is_group]
        return templates.TemplateResponse(request, "transaction_form.html",
                                          {"form": form, "erro": erro, "contas": contas}, status_code=status)

    @app.get("/ui/transactions/new")
    def ui_new_transaction(request: Request, session=Depends(get_session)):
        return _form_page(request, session, {"date": date.today().isoformat()})

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
