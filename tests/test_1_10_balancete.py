import random
from datetime import date, timedelta

from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction, reverse_transaction, trial_balance
from salim.models import Account


def test_balancete_zera_com_lancamentos_aleatorios(session):
    seed_chart(session)
    rng = random.Random(42)
    folhas = [a.code for a in session.query(Account).filter_by(is_group=False).all()]
    ids = []
    for i in range(200):
        n = rng.randint(2, 4)
        contas = rng.sample(folhas, n)
        valores = [rng.randint(1, 100000) for _ in range(n - 1)]
        valores.append(-sum(valores))  # última partida fecha a soma em zero
        tx = post_transaction(
            session, event_date=date(2026, 1, 1) + timedelta(days=i),
            description=f"tx{i}", entries=[Entry(c, v) for c, v in zip(contas, valores)],
        )
        ids.append(tx.id)
    for tx_id in rng.sample(ids, 20):
        reverse_transaction(session, tx_id, event_date=date(2026, 12, 31))

    assert trial_balance(session) == 0


def test_balancete_vazio_e_zero(session):
    seed_chart(session)
    assert trial_balance(session) == 0
