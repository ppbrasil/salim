"""Configuração do plano de contas de despesas e receitas em dois níveis: grupo (`5.NN`/`4.NN`) e linha (`5.NN.MM`).

O plano nasce do padrão (chart.seed_chart) e a pessoa o ajusta: cria grupos e linhas, renomeia, move linhas entre
grupos e arquiva o que não usa. Mover não troca o código: as partidas apontam para o id, então o histórico acompanha.
Linhas soltas no primeiro nível (ex.: `5.99 Outras Despesas`, `4.01 Salário`) continuam valendo; podem ser movidas
para um grupo.
"""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from salim import ledger
from salim.ledger import InvalidAccountError, create_account, get_account, update_account
from salim.models import Account, AccountType, Posting

RAIZ = {"expense": "5", "income": "4"}
TIPO = {"expense": AccountType.EXPENSE, "income": AccountType.INCOME}
RESERVADO = 99          # 5.99 "Outras Despesas": não entra na numeração automática


@dataclass
class ConfigLine:
    code: str
    name: str
    has_postings: bool
    children: list["ConfigLine"] = field(default_factory=list)      # só para contas antigas em 3º nível (somente leitura)


@dataclass
class ConfigGroup:
    code: str
    name: str
    is_group: bool           # False = linha solta no primeiro nível
    has_postings: bool
    lines: list[ConfigLine] = field(default_factory=list)


def _tipo(kind: str) -> str:
    if kind not in RAIZ:
        raise InvalidAccountError("tipo deve ser 'expense' (despesa) ou 'income' (receita)")
    return RAIZ[kind]


def _nome(name: str | None) -> str:
    if not name or not name.strip():
        raise InvalidAccountError("nome não pode ser vazio")
    return name.strip()


def _proximo_codigo(session: Session, parent: Account) -> str:
    prefixo, nivel = parent.code + ".", parent.code.count(".") + 1
    usados = [c for c in session.execute(select(Account.code).where(Account.code.like(prefixo + "%"))).scalars()
              if c.count(".") == nivel]
    nums = [int(c.rsplit(".", 1)[1]) for c in usados if c.rsplit(".", 1)[1].isdigit()]
    n = max((x for x in nums if x < RESERVADO), default=0) + 1
    while f"{prefixo}{n:02d}" in usados:
        n += 1
    return f"{prefixo}{n:02d}"


def _sem_irmao_igual(session: Session, parent: Account, name: str, ignorar: int | None = None) -> None:
    irmaos = session.execute(select(Account).where(Account.parent_id == parent.id, Account.archived.is_(False))).scalars()
    if any(i.id != ignorar and i.name.strip().lower() == name.lower() for i in irmaos):
        raise InvalidAccountError(f"já existe '{name}' em {parent.code} {parent.name}")


def _raiz_de(session: Session, conta: Account) -> Account | None:
    while conta.parent_id is not None:
        conta = session.get(Account, conta.parent_id)
    return conta


def _grupo_de_primeiro_nivel(session: Session, code: str) -> Account:
    g = get_account(session, code)
    pai = session.get(Account, g.parent_id) if g.parent_id else None
    if not g.is_group or pai is None or pai.code not in RAIZ.values():
        raise InvalidAccountError(f"{code} não é um grupo de despesa ou receita")
    return g


def create_group(session: Session, kind: str, name: str) -> Account:
    raiz = get_account(session, _tipo(kind))
    nome = _nome(name)
    _sem_irmao_igual(session, raiz, nome)
    return create_account(session, code=_proximo_codigo(session, raiz), name=nome, type=TIPO[kind],
                          parent_code=raiz.code, is_group=True)


def create_line(session: Session, group_code: str, name: str) -> Account:
    grupo = _grupo_de_primeiro_nivel(session, group_code)
    nome = _nome(name)
    _sem_irmao_igual(session, grupo, nome)
    return create_account(session, code=_proximo_codigo(session, grupo), name=nome, type=grupo.type,
                          parent_code=grupo.code)


def move_line(session: Session, code: str, group_code: str) -> Account:
    conta = get_account(session, code)
    if conta.is_group or conta.type not in (AccountType.EXPENSE, AccountType.INCOME):
        raise InvalidAccountError(f"{code} não é uma linha de despesa ou receita")
    grupo = _grupo_de_primeiro_nivel(session, group_code)
    if grupo.type != conta.type:
        raise InvalidAccountError("o grupo precisa ser do mesmo tipo da linha")
    _sem_irmao_igual(session, grupo, conta.name, ignorar=conta.id)
    return update_account(session, code, parent_code=group_code)


def rename(session: Session, code: str, name: str) -> Account:
    return update_account(session, code, name=_nome(name))


def archive(session: Session, code: str) -> Account:
    return update_account(session, code, archived=True)


def settings_tree(session: Session, kind: str) -> list[ConfigGroup]:
    """Grupos (e linhas soltas) do tipo, cada grupo com suas linhas; arquivadas ficam de fora."""
    raiz = _tipo(kind)
    com_lancamento = set(session.execute(select(Posting.account_id).distinct()).scalars())
    grupos: list[ConfigGroup] = []
    atual: ConfigGroup | None = None
    linha: ConfigLine | None = None
    for depth, c in ledger.account_tree(session, include_archived=False):
        if depth == 0 or not c.code.startswith(raiz + "."):
            continue
        if depth == 1:
            atual = ConfigGroup(c.code, c.name, c.is_group, c.id in com_lancamento)
            grupos.append(atual)
        elif depth == 2 and atual is not None:
            linha = ConfigLine(c.code, c.name, c.id in com_lancamento)
            atual.lines.append(linha)
        elif depth >= 3 and linha is not None:
            linha.children.append(ConfigLine(c.code, c.name, c.id in com_lancamento))
    return grupos
