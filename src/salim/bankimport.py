"""Fila de importação: extrato CSV ou conector bancário → itens pendentes → casar ou lançar."""
import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from salim import ledger, proposals
from salim.models import ImportItem, Posting, Transaction
from salim.money import parse_brl

JANELA_DIAS = 3


class ImportError_(Exception):
    pass


@dataclass
class RawItem:
    date: date
    amount_cents: int            # entrada > 0, saída < 0
    description: str
    external_id: str | None = None


class BankConnector(Protocol):
    """Contrato para Open Finance e afins: devolve os movimentos de uma conta desde uma data."""
    name: str

    def fetch_transactions(self, account_code: str, since: date) -> list[RawItem]: ...


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class ImportResult:
    created: int = 0
    skipped: int = 0
    errors: list[RowError] = field(default_factory=list)


@dataclass
class ItemView:
    id: int
    account_code: str
    date: date
    amount_cents: int
    description: str
    status: str
    transaction_id: int | None


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.strip().lower()) if unicodedata.category(c) != "Mn")


def _cash_account(session: Session, code: str):
    try:
        conta = ledger.get_account(session, code)
    except ledger.AccountNotFoundError:
        raise ImportError_(f"conta inexistente: {code}")
    if not conta.is_cash or conta.is_group:
        raise ImportError_(f"{code} não é uma conta de caixa")
    return conta


def _parse_date(texto: str) -> date:
    t = texto.strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else date.fromisoformat(t)


def _parse_amount(texto: str) -> int:
    t = texto.strip().replace("R$", "").strip()
    if re.fullmatch(r"[-+]?\d+\.\d{1,2}", t):
        t = t.replace(".", ",")
    cents = parse_brl(t)
    if cents == 0:
        raise ValueError("valor zero")
    return cents


def _enqueue(session: Session, conta, itens: list[tuple[RawItem, str]], result: ImportResult) -> None:
    for raw, external_id in itens:
        if session.execute(select(ImportItem.id).where(ImportItem.external_id == external_id)).first():
            result.skipped += 1
            continue
        session.add(ImportItem(account_id=conta.id, external_id=external_id, item_date=raw.date,
                               amount_cents=raw.amount_cents, description=raw.description))
        result.created += 1
    session.commit()


def _hash(*partes) -> str:
    return hashlib.sha1("|".join(map(str, partes)).encode()).hexdigest()[:20]


def import_csv(session: Session, account_code: str, texto: str) -> ImportResult:
    conta = _cash_account(session, account_code)
    linhas = texto.strip().splitlines()
    if not linhas:
        raise ImportError_("arquivo vazio: colunas data, descrição e valor não encontradas")
    sep = ";" if ";" in linhas[0] else ","
    leitor = csv.reader(linhas, delimiter=sep)
    cab = [_norm(c) for c in next(leitor)]

    def achar(nomes):
        return next((i for i, c in enumerate(cab) if c in nomes), None)

    i_data, i_desc, i_valor = achar({"data", "date"}), achar({"descricao", "historico", "description", "memo"}), achar({"valor", "value", "amount"})
    if None in (i_data, i_desc, i_valor):
        raise ImportError_("não encontrei as colunas data, descrição e valor no cabeçalho")
    result, vistos, itens = ImportResult(), {}, []
    for n, row in enumerate(leitor, start=2):
        if not any(c.strip() for c in row):
            continue
        try:
            raw = RawItem(_parse_date(row[i_data]), _parse_amount(row[i_valor]), row[i_desc].strip())
        except (ValueError, IndexError) as e:
            result.errors.append(RowError(n, f"linha inválida ({e})"))
            continue
        chave = (raw.date, raw.amount_cents, raw.description)
        vistos[chave] = vistos.get(chave, 0) + 1
        itens.append((raw, _hash(account_code, raw.date, raw.amount_cents, raw.description, vistos[chave])))
    _enqueue(session, conta, itens, result)
    return result


def sync_connector(session: Session, connector: BankConnector, account_code: str, since: date) -> ImportResult:
    conta = _cash_account(session, account_code)
    result, vistos, itens = ImportResult(), {}, []
    for raw in connector.fetch_transactions(account_code, since):
        if raw.external_id:
            ext = f"{connector.name}:{raw.external_id}"
        else:
            chave = (raw.date, raw.amount_cents, raw.description)
            vistos[chave] = vistos.get(chave, 0) + 1
            ext = f"{connector.name}:{_hash(account_code, *chave, vistos[chave])}"
        itens.append((raw, ext))
    _enqueue(session, conta, itens, result)
    return result


def list_items(session: Session, status: str | None = None) -> list[ItemView]:
    q = select(ImportItem).order_by(ImportItem.item_date, ImportItem.id)
    if status:
        q = q.where(ImportItem.status == status)
    codigos = {a.id: a.code for a in session.scalars(select(ledger.Account))}
    return [ItemView(i.id, codigos[i.account_id], i.item_date, i.amount_cents, i.description, i.status, i.transaction_id)
            for i in session.scalars(q)]


def match_items(session: Session) -> int:
    """Casa itens pendentes com lançamentos já existentes (mesmo valor, até 3 dias de diferença)."""
    usados = set(session.scalars(select(ImportItem.transaction_id).where(ImportItem.transaction_id.is_not(None))))
    casados = 0
    for item in session.scalars(select(ImportItem).where(ImportItem.status == "pending").order_by(ImportItem.item_date, ImportItem.id)):
        cands = session.execute(
            select(Transaction.id, Transaction.event_date).join(Posting, Posting.transaction_id == Transaction.id)
            .where(Posting.account_id == item.account_id, Posting.amount_cents == item.amount_cents,
                   Transaction.event_date.between(item.item_date - timedelta(days=JANELA_DIAS),
                                                  item.item_date + timedelta(days=JANELA_DIAS)))
        ).all()
        cands = sorted((c for c in cands if c.id not in usados), key=lambda c: (abs((c.event_date - item.item_date).days), c.id))
        if cands:
            item.status, item.transaction_id = "matched", cands[0].id
            usados.add(cands[0].id)
            casados += 1
    session.commit()
    return casados


def _pending(session: Session, item_id: int) -> ImportItem:
    item = session.get(ImportItem, item_id)
    if item is None:
        raise ImportError_(f"item inexistente: {item_id}")
    if item.status != "pending":
        raise ImportError_(f"item {item_id} já tratado ({item.status})")
    return item


def book_item(session: Session, item_id: int, counter_account: str) -> int:
    """Cria o lançamento do item contra a conta informada (despesa/receita/outra) e o marca como lançado."""
    item = _pending(session, item_id)
    caixa = session.get(ledger.Account, item.account_id).code
    debito, credito = (counter_account, caixa) if item.amount_cents < 0 else (caixa, counter_account)
    p = proposals.propose_simple(session, event_date=item.item_date, description=item.description,
                                 amount_cents=abs(item.amount_cents), debit_account=debito, credit_account=credito)
    if not p["ok"]:
        raise ImportError_("; ".join(p["errors"]))
    r = proposals.confirm_transaction(session, p, source="import", external_ref=f"import:{item.external_id}")
    item.status, item.transaction_id = "booked", r["transaction_id"]
    session.commit()
    return r["transaction_id"]


def ignore_item(session: Session, item_id: int) -> None:
    _pending(session, item_id).status = "ignored"
    session.commit()
