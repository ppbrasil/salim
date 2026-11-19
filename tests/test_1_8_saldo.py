from datetime import date

from salim.chart import seed_chart
from salim.ledger import Entry, balance, create_account, post_transaction
from salim.models import AccountType


def _setup(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Cartão X", type=AccountType.LIABILITY, parent_code="2.01")
    post_transaction(session, event_date=date(2026, 11, 1), description="Salário",
                     entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    post_transaction(session, event_date=date(2026, 11, 5), description="Aluguel",
                     entries=[Entry("5.01.01", 300000), Entry("1.01.01", -300000)])
    post_transaction(session, event_date=date(2026, 11, 10), description="Luz",
                     entries=[Entry("5.01.03", 20000), Entry("1.01.01", -20000)])
    post_transaction(session, event_date=date(2026, 11, 12), description="Mercado no cartão",
                     entries=[Entry("5.02.01", 50000), Entry("2.01.01", -50000)])


def test_saldo_natural_por_tipo(session):
    _setup(session)
    assert balance(session, "1.01.01") == 180000   # ativo: 5000 - 3000 - 200
    assert balance(session, "4.01") == 500000      # receita cresce a crédito
    assert balance(session, "2.01.01") == 50000    # passivo: devo 500,00
    assert balance(session, "5.01.01") == 300000   # despesa


def test_saldo_ate_uma_data(session):
    _setup(session)
    assert balance(session, "1.01.01", until=date(2026, 11, 4)) == 500000
    assert balance(session, "1.01.01", until=date(2026, 11, 5)) == 200000


def test_grupo_soma_a_subarvore(session):
    _setup(session)
    assert balance(session, "5.01") == 320000      # aluguel + luz
    assert balance(session, "5") == 370000         # + mercado
