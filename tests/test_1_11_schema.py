from sqlalchemy import text


def test_schema_tem_tabelas_views_e_triggers(session):
    nomes = {r[0] for r in session.execute(text("select name from sqlite_master")).all()}
    for n in ["accounts", "transactions", "postings", "obligations", "budget_lines",
              "v_obligation_balance", "v_dre", "v_cash_executed", "v_cash_future", "trg_posting_rules"]:
        assert n in nomes, n


def test_chaves_estrangeiras_ligadas(session):
    assert session.execute(text("pragma foreign_keys")).scalar() == 1
