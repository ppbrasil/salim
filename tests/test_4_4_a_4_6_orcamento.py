import calendar
from datetime import date

import pytest

from salim.budget import BudgetError, budget_vs_actual, effective_budget, set_budget
from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction


def _gasto(session, conta, dia, valor, mes=8):
    post_transaction(session, event_date=date(2026, mes, dia), description=conta,
                     entries=[Entry(conta, valor), Entry("1.01.01", -valor)])


def _por_conta(linhas):
    return {l.code: l for l in linhas}


# ---- 4.4 mês padrão e exceções
def test_mes_padrao_vale_para_qualquer_mes(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 80000)
    for mes in (1, 8, 12):
        assert effective_budget(session, "5.02.01", date(2026, mes, 1)).amount_cents == 80000


def test_mes_especifico_sobrescreve_o_padrao(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 80000)
    set_budget(session, "5.02.01", 120000, month=date(2026, 12, 1))
    assert effective_budget(session, "5.02.01", date(2026, 12, 15)).amount_cents == 120000
    assert effective_budget(session, "5.02.01", date(2026, 11, 1)).amount_cents == 80000


def test_set_budget_atualiza_em_vez_de_duplicar(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 80000)
    set_budget(session, "5.02.01", 90000)
    assert effective_budget(session, "5.02.01", date(2026, 8, 1)).amount_cents == 90000


def test_sem_orcamento_retorna_none(session):
    seed_chart(session)
    assert effective_budget(session, "5.02.01", date(2026, 8, 1)) is None


def test_validacoes(session):
    seed_chart(session)
    with pytest.raises(BudgetError, match="negativo"):
        set_budget(session, "5.02.01", -1)
    with pytest.raises(BudgetError, match="dia"):
        set_budget(session, "5.01.01", 100000, profile="lump")                  # pontual exige dia do mês
    with pytest.raises(BudgetError, match="perfil"):
        set_budget(session, "5.01.01", 100000, profile="outro")
    with pytest.raises(BudgetError, match="despesa ou receita"):
        set_budget(session, "1.01.01", 100000)
    with pytest.raises(BudgetError, match="inexistente"):
        set_budget(session, "9.9.9", 100000)


# ---- 4.5 orçado × realizado
def test_realizado_soma_a_subarvore_pela_competencia(session):
    seed_chart(session)
    set_budget(session, "5.02", 150000)                                         # grupo Alimentação
    _gasto(session, "5.02.01", 3, 40000)
    _gasto(session, "5.02.02", 4, 20000)
    _gasto(session, "5.02.01", 5, 99999, mes=9)                                 # outro mês: fora
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 31)))["5.02"]
    assert (l.budget_cents, l.actual_cents, l.remaining_cents, l.pct_used) == (150000, 60000, 90000, 40)


def test_orcamento_de_mes_fechado_sem_gasto_mostra_restante_total(session):
    seed_chart(session)
    set_budget(session, "5.01.03", 20000)
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 5)))["5.01.03"]
    assert (l.actual_cents, l.remaining_cents, l.pct_used, l.alert) == (0, 20000, 0, "ok")


def test_receita_tambem_pode_ter_meta(session):
    seed_chart(session)
    set_budget(session, "4.01", 500000)
    post_transaction(session, event_date=date(2026, 8, 5), description="Salário",
                     entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 31)))["4.01"]
    assert (l.actual_cents, l.pct_used) == (500000, 100)


# ---- 4.6 perfis e alerta
def test_aluguel_pontual_no_dia_5_nao_alerta(session):
    seed_chart(session)
    set_budget(session, "5.01.01", 200000, profile="lump", day_of_month=5)
    _gasto(session, "5.01.01", 5, 200000)
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 10)))["5.01.01"]
    assert (l.expected_cents, l.alert) == (200000, "ok")


def test_aluguel_pago_adiantado_nao_dispara_alerta_de_ritmo(session):
    seed_chart(session)
    set_budget(session, "5.01.01", 200000, profile="lump", day_of_month=5)
    _gasto(session, "5.01.01", 1, 200000)                                       # pagou antes do dia 5
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 2)))["5.01.01"]
    assert l.alert == "ok"


def test_mercado_acima_do_ritmo_alerta(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 90000)                                       # diluído: 3.000/dia em agosto? não: 90000/31
    _gasto(session, "5.02.01", 5, 60000)
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 10)))["5.02.01"]
    assert l.expected_cents == 90000 * 10 // 31                                 # 10 de 31 dias
    assert l.alert == "acima_do_ritmo"


def test_mercado_dentro_do_ritmo_nao_alerta(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 90000)
    _gasto(session, "5.02.01", 5, 20000)
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 10)))["5.02.01"]
    assert l.alert == "ok"


def test_estourou_o_orcamento(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 90000)
    _gasto(session, "5.02.01", 5, 95000)
    l = _por_conta(budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 31)))["5.02.01"]
    assert (l.alert, l.remaining_cents, l.pct_used) == ("estourado", -5000, 105)


def test_mes_futuro_esperado_zero_e_mes_passado_esperado_total(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 90000)
    assert _por_conta(budget_vs_actual(session, date(2026, 9, 1), today=date(2026, 8, 15)))["5.02.01"].expected_cents == 0
    assert _por_conta(budget_vs_actual(session, date(2026, 7, 1), today=date(2026, 8, 15)))["5.02.01"].expected_cents == 90000


def test_linhas_ordenadas_por_codigo(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 1000)
    set_budget(session, "5.01.01", 1000)
    assert [l.code for l in budget_vs_actual(session, date(2026, 8, 1), today=date(2026, 8, 2))] == ["5.01.01", "5.02.01"]
