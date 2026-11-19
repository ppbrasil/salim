import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, event, func
from sqlalchemy.orm import Mapped, mapped_column

from salim.db import Base


class AccountType(enum.Enum):
    ASSET = "asset"          # ativo: natureza devedora
    LIABILITY = "liability"  # passivo: credora
    EQUITY = "equity"        # patrimônio: credora
    INCOME = "income"        # receita: credora
    EXPENSE = "expense"      # despesa: devedora


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType, values_callable=lambda e: [m.value for m in e]))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    is_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    tracks_obligations: Mapped[bool] = mapped_column(Boolean, default=False)
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    closing_day: Mapped[int | None] = mapped_column(nullable=True)
    due_day: Mapped[int | None] = mapped_column(nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="general")
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    source: Mapped[str] = mapped_column(String, default="web")
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.current_timestamp())


class Obligation(Base):
    """Título: fatura, parcela, boleto, dívida, reembolso. O saldo é a soma das partidas que apontam para ele."""
    __tablename__ = "obligations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    kind: Mapped[str] = mapped_column(String)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    counterparty: Mapped[str | None] = mapped_column(String, nullable=True)
    due_date: Mapped[date] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    installment_no: Mapped[int | None] = mapped_column(nullable=True)
    installment_total: Mapped[int | None] = mapped_column(nullable=True)
    created_by_tx_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))


class Posting(Base):
    __tablename__ = "postings"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount_cents: Mapped[int]  # débito > 0, crédito < 0
    competence_month: Mapped[date] = mapped_column(Date)  # sempre dia 01
    obligation_id: Mapped[int | None] = mapped_column(ForeignKey("obligations.id"), nullable=True)
    memo: Mapped[str | None] = mapped_column(String, nullable=True)


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    month: Mapped[date | None] = mapped_column(Date, nullable=True)  # NULL = mês padrão
    amount_cents: Mapped[int]
    profile: Mapped[str] = mapped_column(String, default="spread")
    day_of_month: Mapped[int | None] = mapped_column(nullable=True)


class ImmutableError(Exception):
    """Lançamentos e partidas nunca são alterados nem apagados; use estorno."""


def _bloqueia(mapper, connection, target):
    raise ImmutableError(f"{type(target).__name__} é imutável; use estorno")


for _model in (Transaction, Posting):
    event.listen(_model, "before_update", _bloqueia)
    event.listen(_model, "before_delete", _bloqueia)
