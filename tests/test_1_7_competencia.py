from datetime import date

from salim.chart import seed_chart
from salim.ledger import Entry, get_account, post_transaction
from salim.models import Posting


def _competencias(session, tx):
    rows = session.query(Posting).filter_by(transaction_id=tx.id).all()
    return {p.account_id: p.competence_date for p in rows}


def test_competencia_default_e_a_data_do_evento(session):
    seed_chart(session)
    tx = post_transaction(session, event_date=date(2026, 11, 5), description="x",
                          entries=[Entry("5.99", 1000), Entry("1.01.01", -1000)])
    comps = _competencias(session, tx)
    assert set(comps.values()) == {date(2026, 11, 5)}


def test_competencia_diferente_por_partida(session):
    seed_chart(session)
    # paga 3 contas de luz atrasadas de uma vez: uma saída de caixa, três competências
    tx = post_transaction(
        session, event_date=date(2026, 11, 5), description="Luz atrasada (3 meses)",
        entries=[
            Entry("5.01.03", 10000, competence_date=date(2026, 8, 1)),
            Entry("5.01.03", 11000, competence_date=date(2026, 9, 1)),
            Entry("5.01.03", 12000, competence_date=date(2026, 10, 1)),
            Entry("1.01.01", -33000),
        ],
    )
    rows = session.query(Posting).filter_by(transaction_id=tx.id).all()
    luz = get_account(session, "5.01.03").id
    assert sorted(p.competence_date for p in rows if p.account_id == luz) == [
        date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]
    caixa = [p for p in rows if p.account_id == get_account(session, "1.01.01").id][0]
    assert caixa.competence_date == date(2026, 11, 5)
