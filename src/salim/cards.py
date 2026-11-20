"""Cartões de crédito: cadastro, fatura aberta sempre e saldo devido (outstanding) por cartão.

Um cartão é uma conta de passivo sob `2.01` que controla títulos (`tracks_obligations`) e tem dia de fechamento e de
vencimento. Cada compra entra na fatura do ciclo (obligations.register_card_purchase). Aqui:
- a fatura aberta do ciclo existe sempre: se ainda não há compra nela, aparece como virtual (valor 0, nada é gravado);
- outstanding = tudo que o cartão deve = fechadas a pagar + aberta + futuras (parcelas de faturas que ainda vão abrir);
  é o número que a conciliação vai comparar com o extrato do cartão.
"""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from salim import obligations as obl
from salim.ledger import InvalidAccountError, create_account, get_account
from salim.models import Account, AccountType, Obligation

BANDEIRAS = {"visa": "Visa", "mastercard": "Mastercard", "master": "Mastercard", "elo": "Elo",
             "american express": "American Express", "amex": "American Express", "hipercard": "Hipercard"}
PAI = "2.01"


@dataclass
class CardInvoice:
    id: int | None            # None = fatura aberta ainda sem compra (virtual)
    reference: str
    closing_date: date
    due_date: date
    balance_cents: int
    status: str               # fechada | aberta | futura
    days_late: int = 0
    virtual: bool = False


@dataclass
class CardSummary:
    code: str
    name: str
    brand: str | None
    last4: str | None
    closing_day: int
    due_day: int
    best_purchase_day: int    # dia seguinte ao fechamento: a compra de hoje cai o mais longe possível
    outstanding_cents: int    # total devido ao cartão
    closed_cents: int         # faturas fechadas, a pagar
    open_cents: int           # fatura aberta (parcial)
    future_cents: int         # parcelas de faturas futuras
    open_closing: date
    open_due: date
    invoices: list[CardInvoice] = field(default_factory=list)


def _dados(name, brand, last4, closing_day, due_day) -> tuple[str, str | None, str | None]:
    if not name or not name.strip():
        raise InvalidAccountError("nome do cartão não pode ser vazio")
    marca = None
    if brand:
        marca = BANDEIRAS.get(brand.strip().lower())
        if marca is None:
            raise InvalidAccountError(f"bandeira desconhecida: {brand} (use {', '.join(sorted(set(BANDEIRAS.values())))})")
    if last4 is not None and not (len(last4) == 4 and last4.isdigit()):
        raise InvalidAccountError("o final do cartão deve ter 4 dígitos")
    return name.strip(), marca, last4


def _proximo_codigo(session: Session) -> str:
    usados = session.execute(select(Account.code).where(Account.code.like(f"{PAI}.%"))).scalars().all()
    n = max((int(c.rsplit(".", 1)[1]) for c in usados if c.rsplit(".", 1)[1].isdigit()), default=0)
    return f"{PAI}.{n + 1:02d}"


def create_card(session: Session, *, name: str, closing_day: int, due_day: int, brand: str | None = None,
                last4: str | None = None, code: str | None = None) -> Account:
    nome, marca, final = _dados(name, brand, last4, closing_day, due_day)
    return create_account(
        session, code=code or _proximo_codigo(session), name=nome, type=AccountType.LIABILITY, parent_code=PAI,
        tracks_obligations=True, closing_day=closing_day, due_day=due_day, card_brand=marca, card_last4=final)


def _cartao(session: Session, code: str) -> Account:
    conta = get_account(session, code)
    if not (conta.type == AccountType.LIABILITY and conta.tracks_obligations and conta.closing_day):
        raise InvalidAccountError(f"{code} não é um cartão de crédito")
    return conta


def update_card(session: Session, code: str, *, name: str | None = None, brand: str | None = None,
                last4: str | None = None, closing_day: int | None = None, due_day: int | None = None) -> Account:
    """Edita os dados do cartão. Fechamento e vencimento novos valem para as faturas que abrirem daqui em diante."""
    conta = _cartao(session, code)
    for dia in (closing_day, due_day):
        if dia is not None and not 1 <= dia <= 31:
            raise InvalidAccountError("dia de fechamento/vencimento deve estar entre 1 e 31")
    nome, marca, final = _dados(name if name is not None else conta.name, brand, last4, closing_day, due_day)
    conta.name = nome
    if brand is not None:
        conta.card_brand = marca
    if last4 is not None:
        conta.card_last4 = final
    if closing_day is not None:
        conta.closing_day = closing_day
    if due_day is not None:
        conta.due_day = due_day
    session.commit()
    return conta


def card_summary(session: Session, code: str, today: date) -> CardSummary:
    conta = _cartao(session, code)
    c0 = obl._closing_on_or_after(today, conta.closing_day)          # fechamento do ciclo em curso
    due0 = obl._due_after(c0, conta.due_day or conta.closing_day)
    faturas: list[CardInvoice] = []
    for v in obl._views(session, today, Obligation.account_id == conta.id):
        if v.kind == "invoice" and v.closing_date is not None:
            if v.closing_date < today:
                status = "fechada"
            elif (v.closing_date.year, v.closing_date.month) == (c0.year, c0.month):
                status = "aberta"
            else:
                status = "futura"
        else:
            status = "fechada"
        if v.balance_cents == 0 and status != "aberta":
            continue                                                # quitada: some da lista
        faturas.append(CardInvoice(v.id, v.reference or "", v.closing_date or v.due_date, v.due_date,
                                   v.balance_cents, status, v.days_late))
    if not any(f.status == "aberta" for f in faturas):
        faturas.append(CardInvoice(None, f"{c0.year}-{c0.month:02d}", c0, due0, 0, "aberta", virtual=True))
    faturas.sort(key=lambda f: (f.closing_date, f.id or 0))
    soma = lambda st: sum(f.balance_cents for f in faturas if f.status == st)
    aberta = next(f for f in faturas if f.status == "aberta")
    return CardSummary(
        code=conta.code, name=conta.name, brand=conta.card_brand, last4=conta.card_last4,
        closing_day=conta.closing_day, due_day=conta.due_day,
        best_purchase_day=1 if conta.closing_day >= 31 else conta.closing_day + 1,
        outstanding_cents=sum(f.balance_cents for f in faturas),
        closed_cents=soma("fechada"), open_cents=soma("aberta"), future_cents=soma("futura"),
        open_closing=aberta.closing_date, open_due=aberta.due_date, invoices=faturas)


def list_cards(session: Session, today: date) -> list[CardSummary]:
    codigos = session.execute(select(Account.code).where(
        Account.type == AccountType.LIABILITY, Account.tracks_obligations.is_(True), Account.is_group.is_(False),
        Account.closing_day.is_not(None), Account.archived.is_(False)).order_by(Account.code)).scalars().all()
    return [card_summary(session, c, today) for c in codigos]
