from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from salim.models import Account, AccountType, ImmutableError, Posting, Transaction  # noqa: F401


class DuplicateAccountError(Exception):
    pass


class AccountNotFoundError(Exception):
    pass


class AlreadyReversedError(Exception):
    pass


class InvalidTransactionError(Exception):
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
    kind: str = "normal",
    is_temporary: bool = False,
) -> Account:
    parent_id = get_account(session, parent_code).id if parent_code else None
    conta = Account(
        code=code, name=name, type=type, parent_id=parent_id,
        is_group=is_group, kind=kind, is_temporary=is_temporary,
    )
    session.add(conta)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DuplicateAccountError(code)
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


@dataclass
class Entry:
    account_code: str
    amount_cents: int  # débito > 0, crédito < 0
    competence_date: date | None = None  # default: data do evento


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
    for conta in contas:
        if conta.is_group:
            raise InvalidTransactionError(f"conta {conta.code} é um grupo e não recebe lançamento")
    tx = Transaction(event_date=event_date, description=description, reverses_id=reverses_id)
    session.add(tx)
    session.flush()
    for e, conta in zip(entries, contas):
        session.add(Posting(
            transaction_id=tx.id, account_id=conta.id, amount_cents=e.amount_cents,
            competence_date=e.competence_date or event_date,
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
        Entry(session.get(Account, p.account_id).code, -p.amount_cents, p.competence_date)
        for p in postings
    ]
    return post_transaction(
        session, event_date=event_date, description=f"Estorno: {original.description}",
        entries=entries, reverses_id=tx_id,
    )


def trial_balance(session: Session) -> int:
    """Soma bruta de todas as partidas do livro. Invariante: sempre 0."""
    return session.execute(select(func.coalesce(func.sum(Posting.amount_cents), 0))).scalar_one()
