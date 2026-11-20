"""Comparativo simples: fatia do grupo no gasto vs. média das famílias brasileiras.

Fonte: IBGE, Pesquisa de Orçamentos Familiares 2017-2018, participação no total das despesas de consumo
(habitação 36,6%; transporte 18,1%; alimentação 17,5%; assistência à saúde 8,0%). É a média do país, de todas as
rendas: famílias mais ricas gastam proporcionalmente menos em alimentação e habitação. Grupos sem referência
(lazer, impostos, encargos, grupos próprios) não são comparados. Sem faixa baixa/alta por falta de dado público
confiável; quando houver base de usuários, a faixa entra aqui.
"""
import unicodedata
from dataclasses import dataclass

FONTE = "IBGE, POF 2017-18"
TOLERANCIA = 0.25            # ±25% sobre a média ainda é "na média"

_REFERENCIA_BPS = {"moradia": 3660, "habitacao": 3660, "transporte": 1810, "alimentacao": 1750, "saude": 800}


@dataclass
class Peer:
    user_pct: float
    ref_pct: float
    label: str            # abaixo da média | na média | acima da média
    basis: str = "orçamento"   # orçamento | gasto


def _norm(nome: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", nome.lower().strip()) if unicodedata.category(c) != "Mn")


def reference_bps(nome: str) -> int | None:
    return _REFERENCIA_BPS.get(_norm(nome))


def position(user_bps: int, ref_bps: int, basis: str = "orçamento") -> Peer:
    razao = user_bps / ref_bps
    rotulo = "abaixo da média" if razao < 1 - TOLERANCIA else "acima da média" if razao > 1 + TOLERANCIA else "na média"
    return Peer(round(user_bps / 100, 1), round(ref_bps / 100, 1), rotulo, basis)
