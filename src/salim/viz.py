"""Gráficos em SVG puro, gerados no servidor (sem JavaScript nem biblioteca externa).

Cores vêm de variáveis CSS (--s1…--s8, ver base.html), na ordem fixa da paleta categórica validada.
Cada marca leva um <title>, que o navegador mostra como dica ao passar o mouse/tocar.
"""
from markupsafe import Markup, escape

from salim.money import brl

MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def mes_curto(ym: str) -> str:
    return f"{MESES[int(ym[5:7]) - 1]}/{ym[2:4]}"


def curto(cents: int) -> str:
    """R$ 12 mil, R$ 1,5 mi — para o eixo."""
    v = abs(cents) / 100
    sinal = "−" if cents < 0 else ""
    if v >= 1_000_000:
        return f"{sinal}R$ {v / 1_000_000:.1f} mi".replace(".", ",")
    if v >= 1000:
        return f"{sinal}R$ {v / 1000:.0f} mil"
    return f"{sinal}R$ {v:.0f}"


def _escala(maximo: int) -> tuple[int, int]:
    """Teto e passo 'redondos' (1, 2 ou 5 × 10^k) com ~4 divisões."""
    if maximo <= 0:
        return 100_00, 25_00
    alvo = maximo / 4
    base = 1
    while base * 10 <= alvo:
        base *= 10
    for m in (1, 2, 5, 10):
        if base * m >= alvo:
            passo = base * m
            break
    teto = passo * (-(-maximo // passo))
    return teto, passo


def _barra(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """Retângulo com os cantos de cima arredondados e a base reta, colada no eixo."""
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h:.1f} Z")


def bar_chart(months: list[str], series: list[tuple[str, int, list[int]]], *, stacked: bool = False,
              height: int = 260, label: str = "") -> Markup:
    """Colunas por mês. series = [(nome, índice da cor 1..8, valores em centavos)]. Valores ≥ 0."""
    n = len(months)
    W, ml, mr, mt, mb = 920, 64, 12, 12, 30
    H = height
    pw, ph = W - ml - mr, H - mt - mb
    totais = [sum(s[2][i] for s in series) for i in range(n)] if stacked else None
    maximo = max(totais) if stacked else max((v for s in series for v in s[2]), default=0)
    teto, passo = _escala(maximo)
    y = lambda c: mt + ph - ph * c / teto
    out = [f'<svg class="viz" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}" preserveAspectRatio="xMidYMid meet">']
    for k in range(0, teto + 1, passo):
        out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y(k):.1f}" y2="{y(k):.1f}" class="grid"/>'
                   f'<text x="{ml - 8}" y="{y(k) + 4:.1f}" class="ax" text-anchor="end">{curto(k)}</text>')
    faixa = pw / max(n, 1)
    grupo = faixa * 0.7
    for i, ym in enumerate(months):
        x0 = ml + faixa * i + (faixa - grupo) / 2
        out.append(f'<text x="{ml + faixa * i + faixa / 2:.1f}" y="{H - 10}" class="ax" text-anchor="middle">{mes_curto(ym)}</text>')
        if stacked:
            base = 0
            for nome, cor, vals in series:
                v = vals[i]
                if v <= 0:
                    continue
                h = ph * v / teto
                out.append(f'<rect x="{x0:.1f}" y="{y(base + v):.1f}" width="{grupo:.1f}" height="{max(h, 0):.1f}" '
                           f'fill="var(--s{cor})" class="seg"><title>{mes_curto(ym)} · {escape(nome)}: {brl(v)}</title></rect>')
                base += v
        else:
            w = grupo / len(series)
            for j, (nome, cor, vals) in enumerate(series):
                v = vals[i]
                if v <= 0:
                    continue
                h = ph * v / teto
                out.append(f'<path d="{_barra(x0 + j * w + 1, y(v), w - 2, h)}" fill="var(--s{cor})" class="seg">'
                           f'<title>{mes_curto(ym)} · {escape(nome)}: {brl(v)}</title></path>')
    out.append("</svg>")
    return Markup("".join(out))


def legend(series: list[tuple[str, int, list[int]]]) -> Markup:
    itens = "".join(f'<span><i style="background:var(--s{c})"></i>{escape(n)}</span>' for n, c, _ in series)
    return Markup(f'<div class="legend">{itens}</div>')


def sparkline(values: list[int], w: int = 90, h: int = 22) -> Markup:
    """Mini-tendência de uma linha da tabela (sem eixos)."""
    if len(values) < 2 or not any(values):
        return Markup("")
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pts = [(2 + (w - 4) * i / (len(values) - 1), h - 3 - (h - 6) * (v - lo) / span) for i, v in enumerate(values)]
    linha = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    x, y = pts[-1]
    return Markup(f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
                  f'<polyline points="{linha}" fill="none" stroke="var(--s1)" stroke-width="2" '
                  f'stroke-linejoin="round" stroke-linecap="round"/>'
                  f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/></svg>')


def line_chart(months: list[str], values: list[int], *, future_from: int | None = None, color: int = 1,
               height: int = 220, label: str = "") -> Markup:
    """Uma série em linha (aceita valores negativos). A partir de `future_from` o traço é tracejado (projeção)."""
    n = len(months)
    W, ml, mr, mt, mb = 920, 64, 24, 14, 30
    H = height
    pw, ph = W - ml - mr, H - mt - mb
    lo, hi = min(0, min(values, default=0)), max(0, max(values, default=0))
    _, passo = _escala(max(abs(lo), abs(hi)))
    teto = passo * (-(-hi // passo)) if hi > 0 else 0
    piso = -passo * (-(-abs(lo) // passo)) if lo < 0 else 0
    if teto == piso:
        teto = passo
    y = lambda c: mt + ph - ph * (c - piso) / (teto - piso)
    x = lambda i: ml + pw * (i + 0.5) / n
    out = [f'<svg class="viz" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}" preserveAspectRatio="xMidYMid meet">']
    k = piso
    while k <= teto:
        out.append(f'<line x1="{ml}" x2="{W - mr}" y1="{y(k):.1f}" y2="{y(k):.1f}" class="{"grid zero" if k == 0 else "grid"}"/>'
                   f'<text x="{ml - 8}" y="{y(k) + 4:.1f}" class="ax" text-anchor="end">{curto(k)}</text>')
        k += passo
    corte = n if future_from is None else future_from
    real = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values[:max(corte, 1)]))
    out.append(f'<polyline points="{real}" fill="none" stroke="var(--s{color})" stroke-width="2" stroke-linejoin="round"/>')
    if future_from is not None and future_from < n:
        ini = max(future_from - 1, 0)
        proj = " ".join(f"{x(i):.1f},{y(values[i]):.1f}" for i in range(ini, n))
        out.append(f'<polyline points="{proj}" fill="none" stroke="var(--s{color})" stroke-width="2" stroke-dasharray="6 4" stroke-linejoin="round"/>')
    for i, (ym, v) in enumerate(zip(months, values)):
        proj = future_from is not None and i >= future_from
        out.append(f'<text x="{x(i):.1f}" y="{H - 10}" class="ax" text-anchor="middle">{mes_curto(ym)}</text>')
        fill = "var(--surface)" if proj else f"var(--s{color})"
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="5" fill="{fill}" style="stroke:var(--s{color})" stroke-width="2" class="seg">'
                   f'<title>{mes_curto(ym)} · saldo{" projetado" if proj else ""}: {brl(v)}</title></circle>')
    out.append("</svg>")
    return Markup("".join(out))
