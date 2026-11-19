from datetime import date

import pytest
from sqlalchemy import func, select

from salim.chart import seed_chart
from salim.ledger import balance
from salim.models import Posting
from salim.obligations import ObligationError, get_obligation, register_bill, settle_obligations


def _luz(session, mes, valor):
    return register_bill(session, event_date=date(2026, mes, 10), description=f"Luz {mes}",
                         expense_account="5.01.03", amount_cents=valor, due_date=date(2026, mes, 20),
                         counterparty="Copel", reference=f"luz {mes}")


def test_registrar_conta_cria_despesa_na_competencia_e_titulo_a_pagar(session):
    seed_chart(session)
    o = _luz(session, 8, 10000)
    v = get_obligation(session, o.id, today=date(2026, 8, 15))
    assert (v.status, v.balance_cents, v.due_date, v.counterparty) == ("a_vencer", 10000, date(2026, 8, 20), "Copel")
    assert balance(session, "5.01.03") == 10000                       # despesa reconhecida, ainda não paga
    assert balance(session, "1.01.01") == 0


def test_pagar_titulo_total(session):
    seed_chart(session)
    o = _luz(session, 8, 10000)
    settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, None)], cash_account_code="1.01.01")
    assert get_obligation(session, o.id, today=date(2026, 8, 21)).status == "quitada"
    assert balance(session, "1.01.01") == -10000


def test_pagamento_parcial_deixa_saldo_que_atrasa(session):
    seed_chart(session)
    o = _luz(session, 8, 10000)
    settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, 2500)], cash_account_code="1.01.01")
    v = get_obligation(session, o.id, today=date(2026, 8, 25))
    assert (v.status, v.balance_cents, v.days_late) == ("atrasada", 7500, 5)


def test_tres_contas_numa_saida_com_multa_e_juros_em_linhas_proprias(session):
    seed_chart(session)
    ids = [_luz(session, m, v).id for m, v in [(8, 10000), (9, 11000), (10, 12000)]]
    tx = settle_obligations(
        session, event_date=date(2026, 11, 5), items=[(i, None) for i in ids], cash_account_code="1.01.01",
        fees=[("5.07.02", 660), ("5.07.01", 300)], description="Luz atrasada (3 meses)")
    assert balance(session, "1.01.01") == -33960
    assert balance(session, "5.07.02") == 660 and balance(session, "5.07.01") == 300
    assert session.execute(select(func.count()).select_from(Posting).where(
        Posting.transaction_id == tx.id, Posting.account_id == 1)).scalar() == 0
    assert all(get_obligation(session, i, today=date(2026, 11, 6)).status == "quitada" for i in ids)


def test_pagar_a_mais_ou_titulo_quitado_e_rejeitado(session):
    seed_chart(session)
    o = _luz(session, 8, 10000)
    with pytest.raises(ObligationError, match="maior que o saldo"):
        settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, 10001)], cash_account_code="1.01.01")
    settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, None)], cash_account_code="1.01.01")
    with pytest.raises(ObligationError, match="sem saldo"):
        settle_obligations(session, event_date=date(2026, 8, 21), items=[(o.id, None)], cash_account_code="1.01.01")
    assert balance(session, "1.01.01") == -10000                       # nada extra gravado
