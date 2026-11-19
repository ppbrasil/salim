import os
from datetime import date
from pathlib import Path

from decimal import Decimal, InvalidOperation

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from salim import ledger
from salim.chart import seed_chart
from salim.db import make_session_factory
from salim.models import Account


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
