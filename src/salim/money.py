"""Formatação e leitura de valores em reais (o sistema guarda centavos inteiros)."""
from decimal import Decimal, InvalidOperation


def brl(cents: int) -> str:
    texto = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}R$ {texto}"


def parse_brl(texto: str) -> int:
    """'3.000,00' -> 300000. Levanta ValueError se não for número."""
    limpo = texto.strip().replace(".", "").replace(",", ".")
    try:
        return int((Decimal(limpo) * 100).to_integral_value())
    except InvalidOperation:
        raise ValueError(texto)
