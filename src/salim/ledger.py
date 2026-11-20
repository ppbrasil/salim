from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from salim.db import sum_cents
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
    card_brand: str | None = None,
    card_last4: str | None = None,
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
        closing_day=closing_day, due_day=due_day, card_brand=card_brand, card_last4=card_last4,
    )
    session.add(conta)
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        if "UNIQUE" in str(e.orig).upper():   # SQLite: "UNIQUE constraint failed"; Postgres: "duplicate key ... unique constraint"
            raise DuplicateAccountError(code)
        raise InvalidAccountError(str(e.orig))
    return conta


def update_account(
    session: Session, code: str, *, name: str | None = None, new_code: str | None = None,
    parent_code: str | None = None, archived: bool | None = None,
) -> Account:
    """Renomeia, troca o código, muda de grupo e/ou arquiva. As partidas apontam para o id: o histórico acompanha.

    Só se arquiva conta de saldo zero (e grupo sem filhas ativas): ela some das telas, mas o histórico fica nos relatórios.
    """
    conta = get_account(session, code)
    if archived:
        if conta.is_group:
            if session.execute(select(Account.id).where(Account.parent_id == conta.id, Account.archived.is_(False))).first():
                raise InvalidAccountError(f"{code} ainda tem contas filhas ativas")
        elif session.execute(select(sum_cents(Posting.amount_cents)).where(Posting.account_id == conta.id)).scalar_one() != 0:
            raise InvalidAccountError(f"{code} tem saldo: zere antes de arquivar")
    if archived is not None:
        conta.archived = archived
    if name is not None:
        if not name.strip():
            raise InvalidAccountError("nome não pode ser vazio")
        conta.name = name.strip()
    if parent_code is not None:
        pai = get_account(session, parent_code)
        if not pai.is_group:
            raise InvalidAccountError(f"{parent_code} não é conta-grupo")
        if pai.type != conta.type:
            raise InvalidAccountError("o grupo precisa ser do mesmo tipo da conta")
        if pai.id == conta.id or pai.id in _subtree_ids(session, conta):
            raise InvalidAccountError("uma conta não pode virar filha de si mesma ou de um descendente")
        conta.parent_id = pai.id
    if new_code is not None and new_code != conta.code:
        conta.code = new_code
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        if "UNIQUE" in str(e.orig).upper():
            raise DuplicateAccountError(new_code)
        raise InvalidAccountError(str(e.orig))
    return conta


def get_account(session: Session, code: str) -> Account:
    conta = session.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if conta is None:
        raise AccountNotFoundError(code)
    return conta


def account_tree(session: Session, include_archived: bool = True) -> list[tuple[int, Account]]:
    """Árvore em ordem de código. Contas arquivadas ficam de fora só quando pedido (telas); relatórios as incluem."""
    q = select(Account).order_by(Account.code)
    if not include_archived:
        q = q.where(Account.archived.is_(False))
    contas = session.execute(q).scalars().all()
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


def _check_entries(session: Session, entries: list[Entry]) -> list[Account]:
    """Valida as partidas (sem tocar no banco) e devolve as contas resolvidas."""
    if len(entries) < 2:
        raise InvalidTransactionError("lançamento precisa de ao menos 2 partidas")
    if any(e.amount_cents == 0 for e in entries):
        raise InvalidTransactionError("partida com valor zero")
    if sum(e.amount_cents for e in entries) != 0:
        raise UnbalancedTransactionError("soma das partidas deve ser zero")
    contas = [get_account(session, e.account_code) for e in entries]
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
    return contas


def new_transaction(
    session: Session, *, event_date: date, description: str, kind: str = "general",
    reverses_id: int | None = None, source: str = "web", external_ref: str | None = None,
) -> Transaction:
    """Abre um lançamento (flush, sem commit). Use post_into para gravar as partidas e fechar."""
    tx = Transaction(event_date=event_date, description=description, kind=kind,
                     reverses_id=reverses_id, source=source, external_ref=external_ref)
    session.add(tx)
    session.flush()
    return tx


def post_into(session: Session, tx: Transaction, entries: list[Entry]) -> Transaction:
    """Valida e grava as partidas de um lançamento já aberto; commit ao final. Em erro, desfaz tudo."""
    try:
        contas = _check_entries(session, entries)
        for e, conta in zip(entries, contas):
            session.add(Posting(
                transaction_id=tx.id, account_id=conta.id, amount_cents=e.amount_cents,
                competence_month=month_start(e.competence or tx.event_date), obligation_id=e.obligation_id,
            ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return tx


def post_transaction(
    session: Session, *, event_date: date, description: str, entries: list[Entry],
    reverses_id: int | None = None, kind: str = "general", source: str = "web",
    external_ref: str | None = None,
) -> Transaction:
    _check_entries(session, entries)  # falha antes de tocar no banco
    tx = new_transaction(session, event_date=event_date, description=description, kind=kind,
                         reverses_id=reverses_id, source=source, external_ref=external_ref)
    return post_into(session, tx, entries)


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
        select(sum_cents(Posting.amount_cents))
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
    return session.execute(select(sum_cents(Posting.amount_cents))).scalar_one()


def balances_all(session: Session) -> dict[int, int]:
    """Saldo natural de todas as contas; grupos somam a subárvore. Uma consulta + soma em memória."""
    proprio = dict(session.execute(
        select(Posting.account_id, sum_cents(Posting.amount_cents)).group_by(Posting.account_id)).all())
    contas = session.execute(select(Account)).scalars().all()
    filhos: dict[int | None, list[Account]] = {}
    for c in contas:
        filhos.setdefault(c.parent_id, []).append(c)

    saldos: dict[int, int] = {}

    def bruto(c: Account) -> int:
        total = proprio.get(c.id, 0) + sum(bruto(f) for f in filhos.get(c.id, []))
        saldos[c.id] = total if c.type in DEBIT_NATURE else -total
        return total

    for raiz in filhos.get(None, []):
        bruto(raiz)
    return saldos


def statement(session: Session, code: str) -> list[dict]:
    """Extrato da conta (ou do grupo, somando a subárvore) com saldo natural corrente."""
    conta = get_account(session, code)
    ids = _subtree_ids(session, conta)
    rows = session.execute(
        select(Posting, Transaction, Account)
        .join(Transaction, Transaction.id == Posting.transaction_id)
        .join(Account, Account.id == Posting.account_id)
        .where(Posting.account_id.in_(ids))
        .order_by(Transaction.event_date, Transaction.id, Posting.id)
    ).all()
    saida, corrente = [], 0
    for p, t, a in rows:
        sinal = 1 if conta.type in DEBIT_NATURE else -1
        delta_na_conta = p.amount_cents * sinal
        corrente += delta_na_conta
        saida.append({
            "transaction_id": t.id, "date": t.event_date.isoformat(), "description": t.description,
            "account_code": a.code, "delta_cents": delta_na_conta, "running_cents": corrente,
            "competence": p.competence_month.isoformat(), "obligation_id": p.obligation_id,
        })
    return saida
