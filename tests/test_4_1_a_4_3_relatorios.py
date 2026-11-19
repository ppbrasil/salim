from datetime import date

from salim.chart import seed_chart
from salim.ledger import Entry, create_account, post_transaction
from salim.models import AccountType
from salim.obligations import (
    consolidate_obligations, installment_obligation, register_bill, register_card_purchase, settle_obligations,
)
from salim.reports import cash_executed, cash_future, dre


def _salario(session, mes, valor=500000):
    post_transaction(session, event_date=date(2026, mes, 5), description="Salário",
                     entries=[Entry("1.01.01", valor), Entry("4.01", -valor)])


def _luz(session, mes, valor, pago=False):
    o = register_bill(session, event_date=date(2026, mes, 10), description="Luz", expense_account="5.01.03",
                      amount_cents=valor, due_date=date(2026, mes, 20), counterparty="Copel")
    if pago:
        settle_obligations(session, event_date=date(2026, mes, 20), items=[(o.id, None)], cash_account_code="1.01.01")
    return o


def _linhas(rel):
    return {l.code: l.amount_cents for l in rel.lines}


# ---- 4.1 DRE por competência
def test_dre_inclui_despesa_nao_paga(session):
    seed_chart(session)
    _salario(session, 8)
    _luz(session, 8, 10000, pago=False)
    r = dre(session, date(2026, 8, 1))
    assert _linhas(r) == {"4.01": 500000, "5.01.03": 10000}
    assert (r.income_cents, r.expense_cents, r.result_cents) == (500000, 10000, 490000)


def test_dre_usa_a_competencia_e_nao_a_data_do_pagamento(session):
    seed_chart(session)
    o = _luz(session, 8, 10000)
    settle_obligations(session, event_date=date(2026, 9, 25), items=[(o.id, None)], cash_account_code="1.01.01")
    assert dre(session, date(2026, 8, 1)).expense_cents == 10000
    assert dre(session, date(2026, 9, 1)).expense_cents == 0


def test_dre_intervalo_soma_meses(session):
    seed_chart(session)
    _luz(session, 8, 10000)
    _luz(session, 9, 12000)
    r = dre(session, date(2026, 8, 1), date(2026, 9, 1))
    assert r.expense_cents == 22000 and _linhas(r) == {"5.01.03": 22000}


def test_dre_juros_e_multa_em_linhas_proprias(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Nubank", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)
    fat = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 6, 28), description="Mercado",
                                 items=[("5.02.01", 110000)])[0]
    parcelas = installment_obligation(session, fat.id, event_date=date(2026, 8, 4), installments=5,
                                      first_due_date=date(2026, 9, 5), interest_cents=10000)
    consolidate_obligations(session, [parcelas[1].id, parcelas[2].id], event_date=date(2026, 11, 19),
                            due_date=date(2026, 11, 30), fine_cents=3000)
    assert _linhas(dre(session, date(2026, 6, 1))) == {"5.02.01": 110000}      # compra fica na competência original
    assert _linhas(dre(session, date(2026, 8, 1))) == {"5.07.01": 10000}
    assert _linhas(dre(session, date(2026, 11, 1))) == {"5.07.02": 3000}


def test_dre_mes_vazio(session):
    seed_chart(session)
    r = dre(session, date(2026, 1, 1))
    assert r.lines == [] and r.result_cents == 0


# ---- 4.2 caixa executado
def test_caixa_executado_so_mexe_com_contas_de_caixa(session):
    seed_chart(session)
    _salario(session, 8)
    _luz(session, 8, 10000, pago=False)                  # despesa não paga: não aparece no caixa
    assert cash_executed(session, date(2026, 8, 1), date(2026, 8, 1))[0].net_cents == 500000
    _luz(session, 9, 12000, pago=True)
    meses = {m.month: m for m in cash_executed(session, date(2026, 8, 1), date(2026, 9, 1))}
    assert (meses["2026-09"].inflow_cents, meses["2026-09"].outflow_cents, meses["2026-09"].net_cents) == (0, 12000, -12000)
    assert meses["2026-08"].inflow_cents == 500000


def test_caixa_executado_lista_meses_sem_movimento(session):
    seed_chart(session)
    _salario(session, 8)
    meses = cash_executed(session, date(2026, 8, 1), date(2026, 10, 1))
    assert [m.month for m in meses] == ["2026-08", "2026-09", "2026-10"]
    assert meses[2].net_cents == 0


# ---- 4.3 caixa futuro
def test_caixa_futuro_usa_data_planejada_ou_vencimento(session):
    seed_chart(session)
    _salario(session, 8)                                 # caixa atual: 5.000,00
    a = _luz(session, 8, 10000)                          # vence 08-20
    b = _luz(session, 9, 12000)                          # vence 09-20
    from salim.obligations import reschedule_obligation
    reschedule_obligation(session, b.id, planned_date=date(2026, 10, 3))   # vou pagar em outubro
    fut = cash_future(session, today=date(2026, 8, 12), months=3)
    assert [m.month for m in fut] == ["2026-08", "2026-09", "2026-10"]
    assert [m.outflow_cents for m in fut] == [10000, 0, 12000]
    assert [m.closing_cents for m in fut] == [490000, 490000, 478000]    # saldo projetado acumulado


def test_caixa_futuro_atrasado_cai_no_mes_corrente_e_pago_some(session):
    seed_chart(session)
    _salario(session, 8)
    a = _luz(session, 7, 10000)                          # venceu 07-20, ainda aberto
    fut = cash_future(session, today=date(2026, 8, 12), months=2)
    assert fut[0].month == "2026-08" and fut[0].outflow_cents == 10000 and fut[0].late_cents == 10000
    settle_obligations(session, event_date=date(2026, 8, 12), items=[(a.id, None)], cash_account_code="1.01.01")
    assert cash_future(session, today=date(2026, 8, 13), months=2)[0].outflow_cents == 0


def test_caixa_futuro_a_receber_entra_como_entrada(session):
    seed_chart(session)
    from salim.obligations import register_reimbursable_expense
    register_reimbursable_expense(session, event_date=date(2026, 7, 22), description="Táxi", expense_account="5.03.01",
                                  my_share_cents=3000, other_share_cents=3000, counterparty="Ana",
                                  due_date=date(2026, 9, 1), payer_account_code="1.01.01")
    fut = cash_future(session, today=date(2026, 8, 12), months=2)
    assert fut[1].month == "2026-09" and fut[1].inflow_cents == 3000
