"""Reservas (conta gráfica): quanto você deveria ter guardado × quanto guardou.

Não mexe no ledger, no caixa nem na DRE: o dinheiro continua nas contas reais; a reserva é uma marcação com aportes e
usos. O gasto de verdade (a viagem, o conserto) é lançado normalmente; o "uso" só baixa a marcação.

Três tipos (os dois primeiros ficam gravados como "goal"):
- meta (goal): valor-alvo numa data. A linha necessária sobe em reta do mês de início até o mês-alvo; o aporte mensal é
  alvo / meses (arredondado para cima).
- troca de um bem (replacement): o que vai trocar (carro, computador, celular...), quando, quanto custa um novo hoje e
  por quanto venderia o usado. O alvo é a perda: novo − usado. Se o bem já existe, "começa em" é o mês da compra e a
  reserva já nasce com a parte vencida em falta (é o que você deveria ter guardado até hoje).
- provisão (provision): aporte mensal fixo, sem fim. A linha necessária é aporte mensal × meses fechados desde o início.

Linha necessária: só conta meses fechados (o mês corrente ainda pode receber o aporte). Falta = necessário − total
aportado (os usos baixam o saldo, não criam falta). Atraso em meses = falta / aporte mensal.
Estado: em_dia (< 0,5 mês), atencao (< 2 meses), deficit (≥ 2 meses). Limites são convenção, ajustáveis aqui.
"""
import unicodedata
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from salim.clock import today as clock_today
from salim.db import sum_cents
from salim.ledger import month_start
from salim.models import Reserve, ReserveMovement

TIPOS = ("goal", "provision", "replacement")
CATEGORIAS = ("carro", "computador", "celular", "eletrodomestico", "outro")
ATENCAO_MESES = 0.5
DEFICIT_MESES = 2.0


class ReserveError(Exception):
    pass


class ReserveNotFound(ReserveError):
    pass


@dataclass
class ReserveStatus:
    id: int
    name: str
    kind: str
    monthly_cents: int
    start_month: date
    target_cents: int | None
    target_date: date | None
    closed_months: int
    total_months: int | None      # só meta
    months_left: int | None       # só meta: meses de hoje (inclusive) até o mês-alvo
    required_cents: int
    funded_cents: int             # total aportado
    used_cents: int
    balance_cents: int            # aportado − usado
    gap_cents: int
    months_behind: float
    state: str                    # em_dia | atencao | deficit
    category: str | None = None   # só troca de bem
    new_price_cents: int | None = None
    resale_cents: int | None = None
    is_replacement: bool = False


@dataclass
class ReserveSummary:
    reserves: list[ReserveStatus]
    total_gap_cents: int
    total_balance_cents: int
    monthly_needed_cents: int     # aportes do mês que mantêm tudo no ritmo
    catch_up_12m_cents: int       # a mais por mês para zerar a falta em 12 meses
    in_deficit: int
    worst: ReserveStatus | None


def _meses(a: date, b: date) -> int:
    """Meses de a até b (primeiros dias), b − a."""
    return (b.year * 12 + b.month) - (a.year * 12 + a.month)


def _categoria(texto: str | None) -> str | None:
    t = "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower().strip()) if unicodedata.category(c) != "Mn")
    return t if t in CATEGORIAS else None


def create_reserve(session: Session, *, name: str, kind: str, start_month: date | None = None,
                   target_cents: int | None = None, target_date: date | None = None,
                   monthly_cents: int | None = None, category: str | None = None,
                   new_price_cents: int | None = None, resale_cents: int | None = None) -> Reserve:
    nome = (name or "").strip()
    if not nome:
        raise ReserveError("nome da reserva não pode ser vazio")
    if kind not in TIPOS:
        raise ReserveError("tipo inválido: use meta (goal), troca de um bem (replacement) ou provisão (provision)")
    inicio = month_start(start_month or clock_today())
    if session.execute(select(Reserve.id).where(Reserve.name == nome, Reserve.archived.is_(False))).first():
        raise ReserveError(f"já existe uma reserva ativa chamada {nome!r}")
    extras = {}
    if kind == "replacement":
        cat = _categoria(category)
        if cat is None:
            raise ReserveError("diga o que vai trocar: carro, computador, celular, eletrodoméstico ou outro")
        if not new_price_cents or new_price_cents <= 0:
            raise ReserveError("diga quanto custa um novo hoje")
        if resale_cents is None or resale_cents < 0:
            raise ReserveError("diga por quanto venderia o seu usado (pode ser zero)")
        if resale_cents >= new_price_cents:
            raise ReserveError("o usado vale tanto quanto um novo: nada a guardar")
        if target_date is None:
            raise ReserveError("diga quando pretende trocar")
        extras = dict(category=cat, new_price_cents=new_price_cents, resale_cents=resale_cents)
        target_cents, kind = new_price_cents - resale_cents, "goal"
    if kind == "goal":
        if not target_cents or target_cents <= 0:
            raise ReserveError("meta exige valor-alvo maior que zero")
        if target_date is None:
            raise ReserveError("meta exige data-alvo")
        if month_start(target_date) < inicio:
            raise ReserveError("data-alvo antes do início da reserva")
        n = _meses(inicio, month_start(target_date)) + 1
        mensal = -(-target_cents // n)
        r = Reserve(name=nome, kind=kind, target_cents=target_cents, target_date=target_date, monthly_cents=mensal,
                    start_month=inicio, **extras)
    else:
        if not monthly_cents or monthly_cents <= 0:
            raise ReserveError("provisão exige aporte mensal maior que zero")
        r = Reserve(name=nome, kind=kind, monthly_cents=monthly_cents, start_month=inicio)
    session.add(r)
    session.commit()
    return r


def _get(session: Session, reserve_id: int) -> Reserve:
    r = session.get(Reserve, reserve_id)
    if r is None:
        raise ReserveNotFound(f"reserva {reserve_id} não existe")
    return r


def archive_reserve(session: Session, reserve_id: int) -> None:
    _get(session, reserve_id).archived = True
    session.commit()


def _totais(session: Session, reserve_id: int) -> tuple[int, int]:
    aportes = session.execute(select(sum_cents(ReserveMovement.amount_cents)).where(
        ReserveMovement.reserve_id == reserve_id, ReserveMovement.amount_cents > 0)).scalar_one() or 0
    usos = session.execute(select(sum_cents(ReserveMovement.amount_cents)).where(
        ReserveMovement.reserve_id == reserve_id, ReserveMovement.amount_cents < 0)).scalar_one() or 0
    return int(aportes), -int(usos)


def add_movement(session: Session, reserve_id: int, *, kind: str, amount_cents: int, movement_date: date,
                 note: str | None = None, transaction_id: int | None = None) -> ReserveMovement:
    r = _get(session, reserve_id)
    if r.archived:
        raise ReserveError("reserva arquivada não recebe movimento")
    if kind not in ("aporte", "uso"):
        raise ReserveError("tipo de movimento inválido: use aporte ou uso")
    if amount_cents is None or amount_cents <= 0:
        raise ReserveError("o valor deve ser maior que zero")
    if kind == "uso":
        aportado, usado = _totais(session, reserve_id)
        if amount_cents > aportado - usado:
            raise ReserveError("uso maior que o saldo da reserva")
    m = ReserveMovement(reserve_id=reserve_id, movement_date=movement_date, note=(note or None) and note.strip(),
                        amount_cents=amount_cents if kind == "aporte" else -amount_cents, transaction_id=transaction_id)
    session.add(m)
    session.commit()
    return m


def reserve_status(session: Session, reserve_id: int, today: date) -> ReserveStatus:
    return _status(session, _get(session, reserve_id), today)


def _status(session: Session, r: Reserve, today: date) -> ReserveStatus:
    fechados = max(0, _meses(r.start_month, month_start(today)))
    total = left = None
    if r.kind == "goal":
        total = _meses(r.start_month, month_start(r.target_date)) + 1
        left = max(0, _meses(month_start(today), month_start(r.target_date)) + 1)
        fechados = min(fechados, total)
        necessario = min(r.target_cents, -(-r.target_cents * fechados // total)) if fechados < total else r.target_cents
    else:
        necessario = r.monthly_cents * fechados
    aportado, usado = _totais(session, r.id)
    falta = max(0, necessario - aportado)
    atraso = round(falta / r.monthly_cents, 1)
    estado = "deficit" if atraso >= DEFICIT_MESES else "atencao" if atraso >= ATENCAO_MESES else "em_dia"
    return ReserveStatus(r.id, r.name, r.kind, r.monthly_cents, r.start_month, r.target_cents, r.target_date, fechados,
                         total, left, necessario, aportado, usado, aportado - usado, falta, atraso, estado,
                         r.category, r.new_price_cents, r.resale_cents, r.new_price_cents is not None)


def summary(session: Session, today: date) -> ReserveSummary:
    ativas = session.execute(select(Reserve).where(Reserve.archived.is_(False)).order_by(Reserve.id)).scalars().all()
    sts = [_status(session, r, today) for r in ativas]
    gap = sum(s.gap_cents for s in sts)
    mensal = sum(s.monthly_cents for s in sts
                 if (s.kind == "provision") or (s.months_left and s.funded_cents < (s.target_cents or 0)))
    pior = max((s for s in sts if s.gap_cents), key=lambda s: (s.months_behind, s.gap_cents), default=None)
    return ReserveSummary(sts, gap, sum(s.balance_cents for s in sts), mensal, -(-gap // 12),
                          sum(1 for s in sts if s.state == "deficit"), pior)
