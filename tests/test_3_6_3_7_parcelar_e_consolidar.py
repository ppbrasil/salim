from collections import defaultdict
from datetime import date

import pytest
from sqlalchemy import select

from salim.chart import seed_chart
from salim.ledger import balance, create_account
from salim.models import Account, AccountType, Posting
from salim.obligations import (
    ObligationError, consolidate_obligations, get_obligation, installment_obligation, list_obligations,
    register_bill, register_card_purchase, settle_obligations,
)


def _despesa_por_competencia(session):
    out = defaultdict(int)
    for comp, conta, cents in session.execute(
            select(Posting.competence_month, Account.code, Posting.amount_cents)
            .join(Account, Account.id == Posting.account_id).where(Account.type == AccountType.EXPENSE)):
        out[(comp.isoformat()[:7], conta)] += cents
    return dict(out)


def _fatura_de_julho(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Nubank", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)
    for d, desc, conta, v in [(date(2026, 6, 28), "Mercado", "5.02.01", 60000),
                              (date(2026, 7, 10), "Restaurante", "5.02.02", 40000),
                              (date(2026, 7, 20), "Assinatura", "5.05.01", 10000)]:
        [inv] = register_card_purchase(session, card_code="2.01.01", event_date=d, description=desc, items=[(conta, v)])
    return inv


def test_parcelar_zera_o_original_e_cria_cronograma_com_juros_em_linha_propria(session):
    inv = _fatura_de_julho(session)
    parcelas = installment_obligation(session, inv.id, event_date=date(2026, 8, 4), installments=5,
                                      first_due_date=date(2026, 9, 5), interest_cents=10000)
    assert get_obligation(session, inv.id, today=date(2026, 8, 4)).status == "quitada"
    assert [(p.installment_no, p.installment_total, p.due_date) for p in parcelas] == [
        (1, 5, date(2026, 9, 5)), (2, 5, date(2026, 10, 5)), (3, 5, date(2026, 11, 5)),
        (4, 5, date(2026, 12, 5)), (5, 5, date(2027, 1, 5))]
    assert [get_obligation(session, p.id, today=date(2026, 8, 4)).balance_cents for p in parcelas] == [24000] * 5
    assert balance(session, "5.07.01") == 10000                       # juros: linha própria
    assert balance(session, "2.04.01") == 120000


def test_nao_parcela_fatura_ainda_aberta(session):
    inv = _fatura_de_julho(session)
    with pytest.raises(ObligationError, match="aberta"):
        installment_obligation(session, inv.id, event_date=date(2026, 7, 21), installments=3,
                               first_due_date=date(2026, 8, 5))


def test_consolidar_zera_originais_e_cria_titulo_novo_com_multa_e_juros_separados(session):
    seed_chart(session)
    ids = [register_bill(session, event_date=date(2026, m, 10), description=f"Luz {m}", expense_account="5.01.03",
                         amount_cents=10000, due_date=date(2026, m, 20)).id for m in (8, 9)]
    novo = consolidate_obligations(session, ids, event_date=date(2026, 11, 19), due_date=date(2026, 11, 30),
                                   fine_cents=400, interest_cents=250)
    hoje = date(2026, 11, 19)
    assert all(get_obligation(session, i, today=hoje).status == "quitada" for i in ids)
    v = get_obligation(session, novo.id, today=hoje)
    assert (v.status, v.balance_cents, v.kind) == ("a_vencer", 20650, "consolidated")
    assert balance(session, "5.07.02") == 400 and balance(session, "5.07.01") == 250
    assert _despesa_por_competencia(session)[("2026-08", "5.01.03")] == 10000   # competência original intacta


def test_nao_consolida_titulo_sem_saldo(session):
    seed_chart(session)
    o = register_bill(session, event_date=date(2026, 8, 10), description="x", expense_account="5.01.03",
                      amount_cents=100, due_date=date(2026, 8, 20))
    settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, None)], cash_account_code="1.01.01")
    with pytest.raises(ObligationError, match="sem saldo"):
        consolidate_obligations(session, [o.id], event_date=date(2026, 9, 1), due_date=date(2026, 9, 30))


def test_cenario_critico_fatura_parcelada_duas_atrasadas_renegociadas_e_liquidadas(session):
    inv = _fatura_de_julho(session)
    antes = _despesa_por_competencia(session)
    assert antes == {("2026-06", "5.02.01"): 60000, ("2026-07", "5.02.02"): 40000, ("2026-07", "5.05.01"): 10000}

    p1, p2, p3, p4, p5 = installment_obligation(
        session, inv.id, event_date=date(2026, 8, 4), installments=5, first_due_date=date(2026, 9, 5),
        interest_cents=10000)
    settle_obligations(session, event_date=date(2026, 9, 5), items=[(p1.id, None)], cash_account_code="1.01.01",
                       description="Parcela 1/5")

    # 18/11: duas parcelas atrasadas
    atrasadas = list_obligations(session, today=date(2026, 11, 18), status="atrasada")
    assert [(v.installment_no, v.days_late) for v in atrasadas] == [(2, 44), (3, 13)]

    # 19/11: renegocia as duas, com multa em linha própria
    novo = consolidate_obligations(session, [p2.id, p3.id], event_date=date(2026, 11, 19),
                                   due_date=date(2026, 11, 30), fine_cents=3000, reference="reneg 2+3")
    v = get_obligation(session, novo.id, today=date(2026, 11, 19))
    assert (v.status, v.balance_cents) == ("a_vencer", 51000)
    assert list_obligations(session, today=date(2026, 11, 19), status="atrasada") == []

    # 30/11: liquida
    settle_obligations(session, event_date=date(2026, 11, 30), items=[(novo.id, None)], cash_account_code="1.01.01")
    abertos = list_obligations(session, today=date(2026, 12, 1))
    assert [(v.installment_no, v.balance_cents) for v in abertos] == [(4, 24000), (5, 24000)]

    # competências originais intactas; só entram juros (ago) e multa (nov), cada um na sua linha
    depois = _despesa_por_competencia(session)
    assert {k: v for k, v in depois.items() if k in antes} == antes
    assert depois[("2026-08", "5.07.01")] == 10000 and depois[("2026-11", "5.07.02")] == 3000
    assert sum(depois.values()) == 110000 + 10000 + 3000
    assert balance(session, "1.01.01") == -(24000 + 51000)
