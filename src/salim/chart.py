from sqlalchemy import select
from sqlalchemy.orm import Session

from salim.ledger import create_account
from salim.models import Account, AccountType as T

CASH = {"is_cash": True}
TRACK = {"tracks_obligations": True}

# (código, nome, tipo, é_grupo, é_temporária, flags). O pai é derivado do código (remove o último segmento).
STANDARD_CHART: list[tuple[str, str, T, bool, bool, dict]] = [
    ("1", "Ativo", T.ASSET, True, False, {}),
    ("1.01", "Caixa e Bancos", T.ASSET, True, False, {}),
    ("1.01.01", "Conta Corrente", T.ASSET, False, False, CASH),
    ("1.01.02", "Carteira (dinheiro)", T.ASSET, False, False, CASH),
    ("1.02", "Investimentos", T.ASSET, True, False, {}),
    ("1.02.01", "Renda Fixa", T.ASSET, False, False, {}),
    ("1.03", "A Receber", T.ASSET, True, False, {}),
    ("1.03.01", "Reembolsos a Receber", T.ASSET, False, True, TRACK),
    ("1.04", "Transição", T.ASSET, True, False, {}),
    ("1.04.01", "Conta de Transição", T.ASSET, False, True, {}),
    ("2", "Passivo", T.LIABILITY, True, False, {}),
    ("2.01", "Cartões de Crédito", T.LIABILITY, True, False, {}),  # cada cartão é uma folha criada pelo usuário
    ("2.02", "Contas a Pagar", T.LIABILITY, True, False, {}),
    ("2.02.01", "Contas a Pagar", T.LIABILITY, False, False, TRACK),
    ("2.03", "Dívidas com Pessoa Jurídica", T.LIABILITY, True, False, {}),
    ("2.03.01", "Dívida com PJ (temporária)", T.LIABILITY, False, True, TRACK),
    ("2.04", "Parcelamentos", T.LIABILITY, True, False, {}),
    ("2.04.01", "Parcelamentos e Renegociações", T.LIABILITY, False, False, TRACK),
    ("3", "Patrimônio", T.EQUITY, True, False, {}),
    ("3.01", "Saldos Iniciais", T.EQUITY, False, False, {}),
    ("4", "Receitas", T.INCOME, True, False, {}),
    ("4.01", "Salário", T.INCOME, False, False, {}),
    ("4.02", "Outras Receitas", T.INCOME, False, False, {}),
    ("5", "Despesas", T.EXPENSE, True, False, {}),
    ("5.01", "Moradia", T.EXPENSE, True, False, {}),
    ("5.01.01", "Aluguel", T.EXPENSE, False, False, {}),
    ("5.01.02", "Condomínio", T.EXPENSE, False, False, {}),
    ("5.01.03", "Luz", T.EXPENSE, False, False, {}),
    ("5.01.04", "Água", T.EXPENSE, False, False, {}),
    ("5.01.05", "Internet", T.EXPENSE, False, False, {}),
    ("5.02", "Alimentação", T.EXPENSE, True, False, {}),
    ("5.02.01", "Supermercado", T.EXPENSE, False, False, {}),
    ("5.02.02", "Restaurantes", T.EXPENSE, False, False, {}),
    ("5.03", "Transporte", T.EXPENSE, True, False, {}),
    ("5.03.01", "Combustível", T.EXPENSE, False, False, {}),
    ("5.04", "Saúde", T.EXPENSE, True, False, {}),
    ("5.04.01", "Plano de Saúde", T.EXPENSE, False, False, {}),
    ("5.05", "Lazer", T.EXPENSE, True, False, {}),
    ("5.05.01", "Assinaturas", T.EXPENSE, False, False, {}),
    ("5.06", "Impostos e Taxas", T.EXPENSE, True, False, {}),
    ("5.07", "Encargos Financeiros", T.EXPENSE, True, False, {}),
    ("5.07.01", "Juros", T.EXPENSE, False, False, {}),
    ("5.07.02", "Multas", T.EXPENSE, False, False, {}),
    ("5.99", "Outras Despesas", T.EXPENSE, False, False, {}),
]


def seed_chart(session: Session) -> None:
    existentes = set(session.execute(select(Account.code)).scalars())
    for code, name, type_, is_group, is_temp, flags in STANDARD_CHART:
        if code in existentes:
            continue
        parent = code.rsplit(".", 1)[0] if "." in code else None
        create_account(
            session, code=code, name=name, type=type_,
            parent_code=parent, is_group=is_group, is_temporary=is_temp, **flags,
        )
