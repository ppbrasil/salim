from datetime import date

from salim.chart import seed_chart
from salim.ledger import Entry, create_account, new_transaction, post_into, post_transaction
from salim.models import AccountType
from salim.obligations import create_obligation, get_obligation, list_obligations


def _fatura(session):
    """Fatura jul/26 (fecha 25/07, vence 05/08) com R$ 600 de compras."""
    seed_chart(session)
    create_account(session, code="2.01.01", name="Cartão", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)
    tx = new_transaction(session, event_date=date(2026, 6, 28), description="Mercado")
    obl = create_obligation(session, tx, account_code="2.01.01", kind="invoice", due_date=date(2026, 8, 5),
                            closing_date=date(2026, 7, 25), reference="2026-07")
    post_into(session, tx, [Entry("5.02.01", 60000), Entry("2.01.01", -60000, obligation_id=obl.id)])
    return obl.id


def _paga(session, obl_id, cents, d):
    post_transaction(session, event_date=d, description="pagamento",
                     entries=[Entry("2.01.01", cents, obligation_id=obl_id), Entry("1.01.01", -cents)])


def test_ciclo_de_vida_da_fatura(session):
    oid = _fatura(session)
    v = get_obligation(session, oid, today=date(2026, 7, 20))
    assert (v.status, v.balance_cents, v.days_late) == ("aberta", 60000, 0)       # ainda recebe compras
    assert get_obligation(session, oid, today=date(2026, 7, 26)).status == "a_vencer"
    assert get_obligation(session, oid, today=date(2026, 8, 5)).status == "a_vencer"   # vence hoje
    v = get_obligation(session, oid, today=date(2026, 8, 6))
    assert (v.status, v.days_late) == ("atrasada", 1)


def test_quitada_e_credito(session):
    oid = _fatura(session)
    _paga(session, oid, 60000, date(2026, 8, 5))
    v = get_obligation(session, oid, today=date(2026, 9, 1))
    assert (v.status, v.balance_cents, v.days_late) == ("quitada", 0, 0)
    _paga(session, oid, 1000, date(2026, 9, 2))
    assert get_obligation(session, oid, today=date(2026, 9, 3)).status == "credito"


def test_saldo_a_receber_do_lado_do_ativo(session):
    seed_chart(session)
    tx = new_transaction(session, event_date=date(2026, 7, 22), description="Jantar")
    r = create_obligation(session, tx, account_code="1.03.01", kind="reimbursement",
                          due_date=date(2026, 8, 30), counterparty="João")
    post_into(session, tx, [Entry("5.02.02", 10000), Entry("1.03.01", 10000, obligation_id=r.id),
                            Entry("1.01.01", -20000)])
    v = get_obligation(session, r.id, today=date(2026, 9, 10))
    assert (v.status, v.balance_cents, v.days_late, v.counterparty) == ("atrasada", 10000, 11, "João")


def test_lista_filtra_por_status_e_ordena_por_vencimento(session):
    oid = _fatura(session)
    seed_extra = new_transaction(session, event_date=date(2026, 7, 1), description="Luz")
    luz = create_obligation(session, seed_extra, account_code="2.02.01", kind="bill", due_date=date(2026, 7, 20))
    post_into(session, seed_extra, [Entry("5.01.03", 10000), Entry("2.02.01", -10000, obligation_id=luz.id)])
    hoje = date(2026, 8, 6)
    todos = list_obligations(session, today=hoje)
    assert [v.due_date for v in todos] == [date(2026, 7, 20), date(2026, 8, 5)]
    atrasadas = list_obligations(session, today=hoje, status="atrasada")
    assert len(atrasadas) == 2 and atrasadas[0].days_late == 17
    _paga(session, oid, 60000, hoje)
    assert [v.id for v in list_obligations(session, today=hoje)] == [luz.id]         # quitadas ficam de fora
    assert len(list_obligations(session, today=hoje, include_settled=True)) == 2
