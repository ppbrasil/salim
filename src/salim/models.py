import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, event, func
from sqlalchemy.orm import Mapped, mapped_column

from salim.db import Base


class AccountType(enum.Enum):
    ASSET = "asset"          # ativo: natureza devedora
    LIABILITY = "liability"  # passivo: natureza credora
    EQUITY = "equity"        # patrimônio: credora
    INCOME = "income"        # receita: credora
    EXPENSE = "expense"      # despesa: devedora


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[AccountType] = mapped_column(Enum(AccountType))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    is_group: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String, default="normal")  # normal | invoice | obligation
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)


class Posting(Base):
    __tablename__ = "postings"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount_cents: Mapped[int]  # débito > 0, crédito < 0
    competence_date: Mapped[date] = mapped_column(Date)


class ImmutableError(Exception):
    """Lançamentos e partidas nunca são alterados nem apagados; use estorno."""


def _bloqueia(mapper, connection, target):
    raise ImmutableError(f"{type(target).__name__} é imutável; use estorno")


for _model in (Transaction, Posting):
    event.listen(_model, "before_update", _bloqueia)
    event.listen(_model, "before_delete", _bloqueia)
