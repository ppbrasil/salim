"""Títulos (obligations): fatura, parcela, boleto, dívida renegociada, reembolso.

O saldo de um título não é coluna: é a soma das partidas que apontam para ele.
"""
import calendar
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from salim.ledger import DEBIT_NATURE, Entry, get_account, new_transaction, post_into
from salim.models import Account, Obligation, Posting, Transaction

KINDS = ("invoice", "bill", "installment", "consolidated", "reimbursement", "other")
STATUSES = ("aberta", "a_vencer", "atrasada", "quitada", "credito")


class ObligationError(Exception):
    pass


@dataclass
class ObligationView:
    id: int
    account_code: str
    kind: str
    reference: str | None
    counterparty: str | None
    due_date: date
    closing_date: date | None
    planned_date: date | None
    installment_no: int | None
    installment_total: int | None
    balance_cents: int
    status: str
    days_late: int
    direction: str  # 'pagar' (passivo) ou 'receber' (ativo)


def create_obligation(
    session: Session, tx: Transaction, *, account_code: str, kind: str, due_date: date,
    reference: str | None = None, counterparty: str | None = None, closing_date: date | None = None,
    planned_date: date | None = None, installment_no: int | None = None, installment_total: int | None = None,
) -> Obligation:
    """Cria o título dentro do lançamento aberto `tx` (flush, sem commit)."""
    if kind not in KINDS:
        raise ObligationError(f"tipo de título inválido: {kind}")
    conta = get_account(session, account_code)
    if not conta.tracks_obligations:
        raise ObligationError(f"conta {account_code} não controla títulos")
    obl = Obligation(
        account_id=conta.id, kind=kind, reference=reference, counterparty=counterparty, due_date=due_date,
        closing_date=closing_date, planned_date=planned_date, installment_no=installment_no,
        installment_total=installment_total, created_by_tx_id=tx.id,
    )
    session.add(obl)
    session.flush()
    return obl


def _status(kind: str, closing: date | None, due: date, balance: int, today: date) -> tuple[str, int]:
    if balance == 0:
        return "quitada", 0
    if balance < 0:
        return "credito", 0
    if kind == "invoice" and closing is not None and closing >= today:
        return "aberta", 0
    if due < today:
        return "atrasada", (today - due).days
    return "a_vencer", 0


def _views(session: Session, today: date, where=None) -> list[ObligationView]:
    q = (
        select(Obligation, Account, func.coalesce(func.sum(Posting.amount_cents), 0))
        .join(Account, Account.id == Obligation.account_id)
        .outerjoin(Posting, Posting.obligation_id == Obligation.id)
        .group_by(Obligation.id)
        .order_by(Obligation.due_date, Obligation.id)
    )
    if where is not None:
        q = q.where(where)
    saida = []
    for o, a, bruto in session.execute(q).all():
        saldo = bruto if a.type in DEBIT_NATURE else -bruto
        st, atraso = _status(o.kind, o.closing_date, o.due_date, saldo, today)
        saida.append(ObligationView(
            id=o.id, account_code=a.code, kind=o.kind, reference=o.reference, counterparty=o.counterparty,
            due_date=o.due_date, closing_date=o.closing_date, planned_date=o.planned_date,
            installment_no=o.installment_no, installment_total=o.installment_total,
            balance_cents=saldo, status=st, days_late=atraso,
            direction="receber" if a.type in DEBIT_NATURE else "pagar"))
    return saida


def get_obligation(session: Session, obligation_id: int, today: date) -> ObligationView:
    achados = _views(session, today, Obligation.id == obligation_id)
    if not achados:
        raise ObligationError(f"título inexistente: {obligation_id}")
    return achados[0]


def list_obligations(
    session: Session, today: date, status: str | None = None, account_code: str | None = None,
    include_settled: bool = False,
) -> list[ObligationView]:
    where = Obligation.account_id == get_account(session, account_code).id if account_code else None
    vistas = _views(session, today, where)
    if status is not None:
        vistas = [v for v in vistas if v.status == status]
    elif not include_settled:
        vistas = [v for v in vistas if v.status != "quitada"]
    return vistas


def _balance(session: Session, obligation_id: int) -> int:
    return get_obligation(session, obligation_id, today=date.today()).balance_cents


def register_bill(
    session: Session, *, event_date: date, description: str, expense_account: str, amount_cents: int,
    due_date: date, payable_account: str = "2.02.01", counterparty: str | None = None,
    reference: str | None = None, competence: date | None = None,
) -> Obligation:
    """Conta a pagar: reconhece a despesa na competência e cria o título com vencimento."""
    tx = new_transaction(session, event_date=event_date, description=description, kind="purchase")
    try:
        obl = create_obligation(session, tx, account_code=payable_account, kind="bill", due_date=due_date,
                                reference=reference, counterparty=counterparty)
    except Exception:
        session.rollback()
        raise
    post_into(session, tx, [Entry(expense_account, amount_cents, competence),
                            Entry(payable_account, -amount_cents, obligation_id=obl.id)])
    return obl


def settle_obligations(
    session: Session, *, event_date: date, items: list[tuple[int, int | None]], cash_account_code: str,
    fees: list[tuple[str, int]] | None = None, description: str = "Pagamento",
) -> Transaction:
    """Quita (total ou parcialmente) um ou mais títulos numa única saída/entrada de caixa.

    items: (id do título, valor em centavos; None = saldo inteiro). fees: (conta de despesa, valor),
    p.ex. multa e juros em linhas separadas. A competência dos títulos nunca é tocada.
    """
    entries: list[Entry] = []
    for oid, valor in items:
        obl = session.get(Obligation, oid)
        if obl is None:
            raise ObligationError(f"título inexistente: {oid}")
        conta = session.get(Account, obl.account_id)
        saldo = _balance(session, oid)
        if saldo <= 0:
            raise ObligationError(f"título {oid} sem saldo para quitar")
        valor = saldo if valor is None else valor
        if valor <= 0:
            raise ObligationError("valor de pagamento deve ser positivo")
        if valor > saldo:
            raise ObligationError(f"valor {valor} maior que o saldo {saldo} do título {oid}")
        sinal = -1 if conta.type in DEBIT_NATURE else 1  # a quitação é o lado oposto da origem
        entries.append(Entry(conta.code, sinal * valor, obligation_id=oid))
    for conta_taxa, valor in fees or []:
        entries.append(Entry(conta_taxa, valor))
    entries.append(Entry(cash_account_code, -sum(e.amount_cents for e in entries)))
    tx = new_transaction(session, event_date=event_date, description=description, kind="payment")
    return post_into(session, tx, entries)


# ------------------------------------------------------------------ cartão de crédito
def _clamp(y: int, m: int, day: int) -> date:
    return date(y, m, min(day, calendar.monthrange(y, m)[1]))


def _shift(y: int, m: int, k: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + k
    return idx // 12, idx % 12 + 1


def _closing_on_or_after(d: date, day: int) -> date:
    c = _clamp(d.year, d.month, day)
    return c if c >= d else _clamp(*_shift(d.year, d.month, 1), day)


def _due_after(closing: date, due_day: int) -> date:
    c = _clamp(closing.year, closing.month, due_day)
    return c if c > closing else _clamp(*_shift(closing.year, closing.month, 1), due_day)


def _invoice_for(session: Session, tx: Transaction, card: Account, closing: date) -> Obligation:
    """Fatura do cartão que fecha em `closing`; abre sozinha se ainda não existe."""
    achada = session.execute(select(Obligation).where(
        Obligation.account_id == card.id, Obligation.kind == "invoice", Obligation.closing_date == closing)
    ).scalar_one_or_none()
    if achada:
        return achada
    return create_obligation(
        session, tx, account_code=card.code, kind="invoice", due_date=_due_after(closing, card.due_day),
        closing_date=closing, reference=f"{closing.year}-{closing.month:02d}")


def register_card_purchase(
    session: Session, *, card_code: str, event_date: date, description: str,
    items: list[tuple[str, int]], installments: int = 1, competence: date | None = None,
) -> list[Obligation]:
    """Compra no cartão: despesa inteira na competência da compra; o crédito vai para a(s) fatura(s).

    Parcelada em N vezes: N créditos em N faturas consecutivas (resto da divisão na primeira).
    """
    card = get_account(session, card_code)
    if not card.tracks_obligations:
        raise ObligationError(f"conta {card_code} não é um cartão (não controla títulos)")
    if not card.closing_day or not card.due_day:
        raise ObligationError(f"cartão {card_code} sem dia de fechamento/vencimento")
    if installments < 1:
        raise ObligationError("número de parcelas deve ser ao menos 1")
    total = sum(v for _, v in items)
    base, resto = divmod(total, installments)
    valores = [base + (resto if k == 0 else 0) for k in range(installments)]
    c0 = _closing_on_or_after(event_date, card.closing_day)

    tx = new_transaction(session, event_date=event_date, description=description, kind="purchase")
    try:
        faturas = [_invoice_for(session, tx, card, _clamp(*_shift(c0.year, c0.month, k), card.closing_day))
                   for k in range(installments)]
    except Exception:
        session.rollback()
        raise
    entries = [Entry(conta, valor, competence) for conta, valor in items]
    entries += [Entry(card_code, -valor, obligation_id=f.id) for valor, f in zip(valores, faturas)]
    post_into(session, tx, entries)
    return faturas


# ------------------------------------------------------------------ parcelar e renegociar
def _debt(session: Session, obligation_id: int) -> tuple[Obligation, Account, int]:
    obl = session.get(Obligation, obligation_id)
    if obl is None:
        raise ObligationError(f"título inexistente: {obligation_id}")
    conta = session.get(Account, obl.account_id)
    if conta.type in DEBIT_NATURE:
        raise ObligationError(f"título {obligation_id} é a receber; só dívidas podem ser parceladas ou renegociadas")
    saldo = _balance(session, obligation_id)
    if saldo <= 0:
        raise ObligationError(f"título {obligation_id} sem saldo")
    return obl, conta, saldo


def _rollback_on_error(session: Session, fn):
    try:
        return fn()
    except Exception:
        session.rollback()
        raise


def installment_obligation(
    session: Session, obligation_id: int, *, event_date: date, installments: int,
    first_due_date: date | None = None, due_dates: list[date] | None = None, interest_cents: int = 0,
    interest_account: str = "5.07.01", target_account: str = "2.04.01",
) -> list[Obligation]:
    """Troca um título (p.ex. fatura fechada) por N parcelas, cada uma com vencimento próprio.

    O original zera; os juros do parcelamento entram em linha própria na competência de hoje;
    as competências das compras originais não são tocadas.
    """
    obl, conta, saldo = _debt(session, obligation_id)
    if obl.kind == "invoice" and obl.closing_date and obl.closing_date >= event_date:
        raise ObligationError("fatura ainda aberta: só dá para parcelar depois do fechamento")
    if due_dates is None:
        if first_due_date is None or installments < 1:
            raise ObligationError("informe first_due_date (ou due_dates) e ao menos 1 parcela")
        due_dates = [_clamp(*_shift(first_due_date.year, first_due_date.month, k), first_due_date.day)
                     for k in range(installments)]
    if len(due_dates) != installments:
        raise ObligationError("due_dates deve ter uma data por parcela")
    total = saldo + interest_cents
    base, resto = divmod(total, installments)
    valores = [base + (resto if k == 0 else 0) for k in range(installments)]

    tx = new_transaction(session, event_date=event_date, kind="consolidation",
                         description=f"Parcelamento de {obl.reference or 'título ' + str(obl.id)} em {installments}x")

    def montar():
        parcelas = [create_obligation(session, tx, account_code=target_account, kind="installment", due_date=d,
                                      reference=f"parc {k}/{installments}", installment_no=k, installment_total=installments)
                    for k, d in enumerate(due_dates, 1)]
        entries = [Entry(conta.code, saldo, obligation_id=obl.id)]
        if interest_cents:
            entries.append(Entry(interest_account, interest_cents))
        entries += [Entry(target_account, -v, obligation_id=p.id) for v, p in zip(valores, parcelas)]
        post_into(session, tx, entries)
        return parcelas

    return _rollback_on_error(session, montar)


def consolidate_obligations(
    session: Session, obligation_ids: list[int], *, event_date: date, due_date: date,
    fine_cents: int = 0, interest_cents: int = 0, fine_account: str = "5.07.02",
    interest_account: str = "5.07.01", target_account: str = "2.04.01",
    reference: str | None = None, counterparty: str | None = None,
) -> Obligation:
    """Renegociação: quita N títulos e cria um único título novo (multa e juros em linhas próprias)."""
    if not obligation_ids:
        raise ObligationError("nenhum título informado")
    if len(set(obligation_ids)) != len(obligation_ids):
        raise ObligationError("título repetido na lista")
    dividas = [_debt(session, oid) for oid in obligation_ids]
    total = sum(s for _, _, s in dividas) + fine_cents + interest_cents
    tx = new_transaction(session, event_date=event_date, kind="consolidation",
                         description=f"Renegociação de {len(dividas)} título(s)")

    def montar():
        novo = create_obligation(session, tx, account_code=target_account, kind="consolidated", due_date=due_date,
                                 reference=reference, counterparty=counterparty)
        entries = [Entry(c.code, s, obligation_id=o.id) for o, c, s in dividas]
        if fine_cents:
            entries.append(Entry(fine_account, fine_cents))
        if interest_cents:
            entries.append(Entry(interest_account, interest_cents))
        entries.append(Entry(target_account, -total, obligation_id=novo.id))
        post_into(session, tx, entries)
        return novo

    return _rollback_on_error(session, montar)


# ------------------------------------------------------------------ reembolso e remarcação
def register_reimbursable_expense(
    session: Session, *, event_date: date, description: str, expense_account: str, my_share_cents: int,
    other_share_cents: int, counterparty: str, due_date: date, payer_account_code: str,
    receivable_account: str = "1.03.01", reference: str | None = None,
) -> Obligation:
    """Despesa dividida: só a minha parte é despesa; a do outro vira título a receber.

    O pagador pode ser caixa (saída imediata) ou cartão (o total entra na fatura).
    """
    if other_share_cents <= 0 or my_share_cents < 0:
        raise ObligationError("parte do outro deve ser positiva e a minha não pode ser negativa")
    payer = get_account(session, payer_account_code)
    if payer.tracks_obligations and (not payer.closing_day or not payer.due_day):
        raise ObligationError(f"cartão {payer_account_code} sem dia de fechamento/vencimento")
    total = my_share_cents + other_share_cents
    tx = new_transaction(session, event_date=event_date, description=description, kind="purchase")

    def montar():
        receber = create_obligation(session, tx, account_code=receivable_account, kind="reimbursement",
                                    due_date=due_date, counterparty=counterparty, reference=reference)
        entries = [Entry(expense_account, my_share_cents)] if my_share_cents else []
        entries.append(Entry(receivable_account, other_share_cents, obligation_id=receber.id))
        if payer.tracks_obligations:
            fatura = _invoice_for(session, tx, payer, _closing_on_or_after(event_date, payer.closing_day))
            entries.append(Entry(payer_account_code, -total, obligation_id=fatura.id))
        else:
            entries.append(Entry(payer_account_code, -total))
        post_into(session, tx, entries)
        return receber

    return _rollback_on_error(session, montar)


def reschedule_obligation(
    session: Session, obligation_id: int, *, due_date: date | None = None,
    planned_date: date | None = None, clear_planned: bool = False,
) -> Obligation:
    """Remarca vencimento e/ou data planejada. Nada além disso muda num título."""
    obl = session.get(Obligation, obligation_id)
    if obl is None:
        raise ObligationError(f"título inexistente: {obligation_id}")
    if due_date is not None:
        obl.due_date = due_date
    if clear_planned:
        obl.planned_date = None
    elif planned_date is not None:
        obl.planned_date = planned_date
    session.commit()
    return obl
