"""Entrada da Vercel (função Python): expõe `app`, uma aplicação ASGI.

O schema e o plano de contas NÃO são criados aqui: rodam fora da função, com `python -m salim.migrate --seed`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from salim.app import create_app  # noqa: E402
from salim.vercel_path import RestaurarCaminhoOriginal  # noqa: E402

# a Vercel entrega /api/index; o caminho real vem em ?__p= (ver vercel.json)
app = RestaurarCaminhoOriginal(create_app(seed=False))
