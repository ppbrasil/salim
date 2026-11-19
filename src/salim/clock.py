"""O "hoje" do sistema: o dia em São Paulo (SALIM_TZ), não o dia UTC do servidor.

Na Vercel o relógio do processo é UTC; sem isto, depois das 21h em Brasília tudo já seria "amanhã"
(fatura venceria um dia antes, orçamento do dia seguinte).
"""
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Sao_Paulo"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return _utcnow().astimezone(ZoneInfo(os.environ.get("SALIM_TZ", DEFAULT_TZ))).date()
