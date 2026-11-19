from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from salim.models import Account, AccountType, ImmutableError, Obligation, Posting, Transaction  # noqa: F401


class DuplicateAccountError(Exception):
    pass


class AccountNotFoundError(Exception):
    pass


class AlreadyReversedError(Exception):
    pass


class InvalidAccountError(Exception):
    pass


class InvalidTransactionError(Exception):
    pass


class MissingObligationError(InvalidTransactionError):
    pass


class UnbalancedTransactionError(InvalidTransactionError):
    pass


def create_account(
    session: Session,
    *,
    code: str,
    name: str,
    type: AccountType,
    parent_code: str | None = None,
    is_group: bool = False,
    is_cash: bool = False,
    tracks_obligations: bool = False,
    is_temporary: bool = False,
    closing_day: int | None = None,
    due_day: int | None = None,
) -> Account:
    if is_group and (is_cash or tracks_obligations):
        raise InvalidAccountError("conta-grupo não pode ser caixa nem controlar títulos")
    for dia in (closing_day, due_day):
        if dia is not None and not 1 <= dia <= 31:
            raise InvalidAccountError("dia de fechamento/vencimento deve estar entre 1 e 31")
    parent_id = get_account(session, parent_code).id if parent_code else None
    conta = Account(
        code=code, name=name, type=type, parent_id=parent_id, is_group=is_group, is_cash=is_cash,
        tracks_obligations=tracks_obligations, is_temporary=is_temporary,
        closing_day=closing_day, due_day=due_day,
    )
    session.add(conta)
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        if "UNIQUE" in str(e.orig):
            raise DuplicateAccountError(code)
        raise InvalidAccountError(str(e.orig))
    return conta


def get_account(session: Session, code: str) -> Account:
    conta = session.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if conta is None:
        raise AccountNotFoundError(code)
    return conta


def account_tree(session: Session) -> list[tuple[int, Account]]:
    contas = session.execute(select(Account).order_by(Account.code)).scalars().all()
    filhos: dict[int | None, list[Account]] = {}
    for c in contas:
        filhos.setdefault(c.parent_id, []).append(c)

    saida: list[tuple[int, Account]] = []

    def visitar(parent_id: int | None, depth: int) -> None:
        for c in filhos.get(parent_id, []):
            saida.append((depth, c))
            visitar(c.id, depth + 1)

    visitar(None, 0)
    return saida


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


@dataclass
class Entry:
    account_code: str
    amount_cents: int  # débito > 0, crédito < 0
    competence: date | None = None  # qualquer dia do mês; default: mês do evento
    obligation_id: int | None = None  # obrigatório em conta que controla títulos


def post_transaction(
    session: Session, *, event_date: date, description: str, entries: list[Entry],
    reverses_id: int | None = None,
) -> Transaction:
    if len(entries) < 2:
        raise InvalidTransactionError("lançamento precisa de ao menos 2 partidas")
    if any(e.amount_cents == 0 for e in entries):
        raise InvalidTransactionError("partida com valor zero")
    if sum(e.amount_cents for e in entries) != 0:
        raise UnbalancedTransactionError("soma das partidas deve ser zero")
    contas = [get_account(session, e.account_code) for e in entries]  # falha antes de tocar no banco
    for e, conta in zip(entries, contas):
        if conta.is_group:
            raise InvalidTransactionError(f"conta {conta.code} é um grupo e não recebe lançamento")
        if conta.tracks_obligations and e.obligation_id is None:
            raise MissingObligationError(f"conta {conta.code} exige título (obligation_id)")
        if e.obligation_id is not None:
            if not conta.tracks_obligations:
                raise InvalidTransactionError(f"conta {conta.code} não controla títulos")
            obl = session.get(Obligation, e.obligation_id)
            if obl is None or obl.account_id != conta.id:
                raise InvalidTransactionError(f"título {e.obligation_id} não pertence à conta {conta.code}")
    tx = Transaction(event_date=event_date, description=description, reverses_id=reverses_id)
    session.add(tx)
    session.flush()
    for e, conta in zip(entries, contas):
        session.add(Posting(
            transaction_id=tx.id, account_id=conta.id, amount_cents=e.amount_cents,
            competence_month=month_start(e.competence or event_date), obligation_id=e.obligation_id,
        ))
    session.commit()
    return tx


DEBIT_NATURE = (AccountType.ASSET, AccountType.EXPENSE)


def _subtree_ids(session: Session, root: Account) -> list[int]:
    ids, fila = [], [root.id]
    while fila:
        atual = fila.pop()
        ids.append(atual)
        fila.extend(session.execute(select(Account.id).where(Account.parent_id == atual)).scalars())
    return ids


def balance(session: Session, code: str, until: date | None = None) -> int:
    """Saldo natural (positivo = no sentido normal da conta), pela data do evento."""
    conta = get_account(session, code)
    q = (
        select(func.coalesce(func.sum(Posting.amount_cents), 0))
        .join(Transaction, Transaction.id == Posting.transaction_id)
        .where(Posting.account_id.in_(_subtree_ids(session, conta)))
    )
    if until is not None:
        q = q.where(Transaction.event_date <= until)
    bruto = session.execute(q).scalar_one()
    return bruto if conta.type in DEBIT_NATURE else -bruto


def reverse_transaction(session: Session, tx_id: int, *, event_date: date) -> Transaction:
    original = session.get(Transaction, tx_id)
    if session.execute(select(Transaction.id).where(Transaction.reverses_id == tx_id)).first():
        raise AlreadyReversedError(tx_id)
    postings = session.execute(select(Posting).where(Posting.transaction_id == tx_id)).scalars().all()
    entries = [
        Entry(session.get(Account, p.account_id).code, -p.amount_cents, p.competence_month, p.obligation_id)
        for p in postings
    ]
    return post_transaction(
        session, event_date=event_date, description=f"Estorno: {original.description}",
        entries=entries, reverses_id=tx_id,
    )


def trial_balance(session: Session) -> int:
    """Soma bruta de todas as partidas do livro. Invariante: sempre 0."""
    return session.execute(select(func.coalesce(func.sum(Posting.amount_cents), 0))).scalar_one()
