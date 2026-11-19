"""Texto livre → proposta de lançamento. Regras determinísticas primeiro; LLM entra só como `fallback` plugável."""
import re
import unicodedata
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from salim import proposals
from salim.models import Account
from salim.money import parse_brl

CASH = "1.01.01"
STOP = {"gastei", "paguei", "comprei", "gasto", "no", "na", "nos", "nas", "de", "do", "da", "em", "com", "hoje",
        "ontem", "anteontem", "recebi", "r$", "reais", "real", "um", "uma", "o", "a", "pra", "para"}
# (prefixos de palavra, conta). Mais específico primeiro; receitas antes de despesas.
KEYWORDS = [
    (("salario",), "4.01"), (("recebi", "recebimento", "freela"), "4.02"),
    (("mercado", "supermercado", "hortifruti", "feira"), "5.02.01"),
    (("restaurante", "almoco", "jantar", "lanche", "pizza", "ifood", "cafe"), "5.02.02"),
    (("gasolina", "combustivel", "etanol", "posto"), "5.03.01"),
    (("luz", "energia"), "5.01.03"), (("agua",), "5.01.04"), (("internet", "wifi"), "5.01.05"),
    (("aluguel",), "5.01.01"), (("condominio",), "5.01.02"), (("plano",), "5.04.01"),
    (("assinatura", "netflix", "spotify"), "5.05.01"),
]
_NUM = re.compile(r"(?<![\d/.,])(\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?:\.\d{3})+(?![\d,])|\d+[.,]\d{1,2}(?![\d/])|\d+(?![\d/]))")
_DATA = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)")


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _amount(texto: str) -> tuple[int, str] | None:
    m = _NUM.search(texto)
    if not m:
        return None
    bruto = m.group(1)
    if re.fullmatch(r"\d+\.\d{1,2}", bruto):
        bruto = bruto.replace(".", ",")
    cents = parse_brl(bruto)
    return (cents, m.group(1)) if cents > 0 else None


def _event_date(norm: str, today: date) -> date:
    if "anteontem" in norm:
        return today - timedelta(days=2)
    if "ontem" in norm:
        return today - timedelta(days=1)
    m = _DATA.search(norm)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
            return d if d <= today else date(today.year - 1, d.month, d.day)
        except ValueError:
            pass
    return today


def _description(texto: str, token_valor: str) -> str:
    ficam = [w for w in texto.split()
             if _norm(w) not in STOP and w != token_valor and not _DATA.fullmatch(w) and w.lower() != "r$"]
    return (" ".join(ficam) or texto).strip().capitalize()


def _by_keyword(norm: str) -> str | None:
    palavras = re.findall(r"[a-z0-9]+", norm)
    for prefixos, conta in KEYWORDS:
        if any(p.startswith(k) for p in palavras for k in prefixos):
            return conta
    return None


def suggest_account(session: Session, texto: str) -> str | None:
    """Conta de despesa/receita mais usada em lançamentos anteriores com palavra parecida."""
    palavras = {w for w in re.findall(r"[a-z]+", _norm(texto)) if len(w) >= 4 and w not in STOP}
    uso: Counter = Counter()
    for w in palavras:
        rows = session.execute(text("""
            SELECT a.code FROM postings p
            JOIN transactions t ON t.id = p.transaction_id
            JOIN accounts a ON a.id = p.account_id AND a.type IN ('expense', 'income')
            WHERE lower(t.description) LIKE :w"""), {"w": f"%{w}%"}).scalars()
        uso.update(rows)
    return uso.most_common(1)[0][0] if uso else None


def _proposal(session: Session, conta: str, cents: int, desc: str, dia: date) -> dict:
    tipo = session.query(Account.type).filter(Account.code == conta).scalar()
    if tipo is not None and tipo.value == "income":
        return proposals.propose_simple(session, event_date=dia, description=desc, amount_cents=cents,
                                        debit_account=CASH, credit_account=conta)
    return proposals.propose_simple(session, event_date=dia, description=desc, amount_cents=cents,
                                    debit_account=conta, credit_account=CASH)


def parse_entry_text(session: Session, texto: str, today: date, fallback=None) -> dict | None:
    """None se não parece um lançamento (sem valor). Senão uma proposta; ok=False se faltou categoria."""
    achado = _amount(texto)
    if achado is None:
        return None
    cents, token = achado
    norm = _norm(texto)
    dia, desc = _event_date(norm, today), _description(texto, token)
    conta = _by_keyword(norm) or suggest_account(session, texto)
    if conta:
        return _proposal(session, conta, cents, desc, dia)
    if fallback is not None:
        r = fallback(texto, today, session)
        if r:
            return proposals.propose_simple(
                session, event_date=r.get("event_date", dia), description=r.get("description", desc),
                amount_cents=r["amount_cents"], debit_account=r["debit_account"], credit_account=r["credit_account"])
    return {"ok": False, "errors": ["categoria não identificada"], "event_date": dia.isoformat(),
            "description": desc, "entries": []}
