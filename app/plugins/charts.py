"""Grafici SVG generati sul server (nessuna libreria nel browser, funzionano anche in stampa).

I colori sono classi CSS (s1…s8) definite in plugins.css, così seguono il tema chiaro/scuro.
"""
from __future__ import annotations

import html
import math
from typing import Any

from .tabledata import Table, TableError, _num, fmt_number, fmt_value

W, H = 680, 300
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 16, 56
MAX_CATS = 60
TYPES = ("bar", "hbar", "line", "area", "pie", "donut", "stacked")


def _e(s: Any) -> str:
    return html.escape(str(s), quote=True)


def _short(s: str, n: int = 16) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _nice(lo: float, hi: float, ticks: int = 5) -> tuple[float, float, float]:
    if hi == lo:
        hi = lo + (abs(lo) or 1)
    span = hi - lo
    raw = span / ticks
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return math.floor(lo / step) * step, math.ceil(hi / step) * step, step


def _tick(v: float) -> str:
    a = abs(v)
    if a >= 1_000_000:
        return fmt_number(v / 1_000_000, 1 if v % 1_000_000 else 0) + " Mln"
    if a >= 10_000:
        return fmt_number(v / 1000, 0) + "k"
    return fmt_number(v, 0 if float(v).is_integer() else 1)


def render_chart(table: Table, kind: str, x: str = "", ys: list[str] | None = None, title: str = "",
                 fmts: dict | None = None, multi_default: bool = False) -> str:
    kind = (kind or "bar").lower()
    kind = {"barre": "bar", "colonne": "bar", "barre-orizzontali": "hbar", "linea": "line", "torta": "pie",
            "ciambella": "donut", "area": "area", "impilato": "stacked"}.get(kind, kind)
    if kind not in TYPES:
        raise TableError(f"Tipo di grafico «{kind}» sconosciuto. Usa: {', '.join(TYPES)}")
    if not table.rows:
        return ""
    xi = table.index(x) if x else next((i for i in range(len(table.columns)) if not table.is_numeric(i)), 0)
    if ys:
        yi = [table.index(y) for y in ys]
    else:
        yi = [i for i in range(len(table.columns)) if i != xi and table.is_numeric(i)]
        if multi_default:  # pivot: una serie per colonna, senza la colonna «Totale»
            yi = [i for i in yi if table.columns[i].strip().lower() != "totale"] or yi
            yi = yi[:8]
        else:  # altrimenti la prima colonna numerica (per più serie: «y: [A, B]»)
            yi = yi[:1]
    if not yi:
        raise TableError("Per il grafico serve almeno una colonna numerica (indica «y:»).")
    rows = table.rows[:MAX_CATS]
    labels = [fmt_value(r[xi]) if xi < len(r) else "" for r in rows]
    series = [(table.columns[i], [(_num(r[i]) if i < len(r) else None) for r in rows]) for i in yi]
    fmt = (fmts or {}).get(table.columns[yi[0]], "")
    if kind in ("pie", "donut"):
        svg = _pie(labels, series[0][1], kind == "donut", fmt)
    elif kind == "hbar":
        svg = _hbar(labels, series, fmt)
    else:
        svg = _xy(labels, series, kind, fmt)
    legend = ""
    if len(series) > 1 and kind not in ("pie", "donut"):
        legend = '<div class="dt-legend">' + "".join(
            f'<span><i class="s{n % 8 + 1}"></i>{_e(name)}</span>' for n, (name, _) in enumerate(series)) + "</div>"
    cap = f'<div class="dt-chart-title">{_e(title)}</div>' if title else ""
    return f'<div class="dt-chart">{cap}{svg}{legend}</div>'


def _xy(labels, series, kind, fmt) -> str:
    n = len(labels)
    stacked = kind == "stacked"
    vals = [v for _, s in series for v in s if v is not None]
    if stacked:
        sums = [sum((s[i] or 0) for _, s in series if (s[i] or 0) > 0) for i in range(n)]
        negs = [sum((s[i] or 0) for _, s in series if (s[i] or 0) < 0) for i in range(n)]
        vals = sums + negs
    lo, hi = min(vals + [0]), max(vals + [0])
    lo, hi, step = _nice(lo, hi)
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    yv = lambda v: PAD_T + ph - (v - lo) / (hi - lo) * ph  # noqa: E731
    out = [f'<svg class="dt-svg" viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">']
    t = lo
    while t <= hi + step / 2:
        y = yv(t)
        out.append(f'<line class="grid{" zero" if abs(t) < 1e-12 else ""}" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end">{_e(_tick(t))}</text>')
        t += step
    band = pw / max(n, 1)
    rotate = n > 8 or max((len(lb) for lb in labels), default=0) * 7 > band
    every = max(1, math.ceil(n / 24))
    for i, lb in enumerate(labels):
        if i % every:
            continue
        cx = PAD_L + band * (i + .5)
        if rotate:
            out.append(f'<text class="tick" transform="translate({cx:.1f},{H - PAD_B + 12}) rotate(-35)" text-anchor="end">{_e(_short(lb, 14))}<title>{_e(lb)}</title></text>')
        else:
            out.append(f'<text class="tick" x="{cx:.1f}" y="{H - PAD_B + 18}" text-anchor="middle">{_e(_short(lb, 18))}<title>{_e(lb)}</title></text>')
    if kind in ("bar", "stacked"):
        k = 1 if stacked else len(series)
        bw = band * .72 / k
        base_pos = [0.0] * n
        base_neg = [0.0] * n
        for si, (name, s) in enumerate(series):
            for i, v in enumerate(s):
                if v is None:
                    continue
                if stacked:
                    b0 = base_pos[i] if v >= 0 else base_neg[i]
                    y0, y1 = yv(b0), yv(b0 + v)
                    if v >= 0:
                        base_pos[i] += v
                    else:
                        base_neg[i] += v
                    x0 = PAD_L + band * i + band * .14
                else:
                    y0, y1 = yv(0), yv(v)
                    x0 = PAD_L + band * i + band * .14 + bw * si
                top, h = min(y0, y1), abs(y1 - y0)
                out.append(f'<rect class="s{si % 8 + 1}" x="{x0:.1f}" y="{top:.1f}" width="{max(bw - 1, 1):.1f}" '
                           f'height="{max(h, .5):.1f}" rx="2"><title>{_e(labels[i])} · {_e(name)}: {_e(fmt_value(v, fmt))}</title></rect>')
    else:
        for si, (name, s) in enumerate(series):
            pts = [(PAD_L + band * (i + .5), yv(v), v, i) for i, v in enumerate(s) if v is not None]
            if not pts:
                continue
            d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y, _, _) in enumerate(pts))
            if kind == "area":
                out.append(f'<path class="area s{si % 8 + 1}" d="{d} L{pts[-1][0]:.1f},{yv(max(lo, 0)):.1f} L{pts[0][0]:.1f},{yv(max(lo, 0)):.1f} Z"/>')
            out.append(f'<path class="line s{si % 8 + 1}" d="{d}"/>')
            if len(pts) <= 40:
                for x, y, v, i in pts:
                    out.append(f'<circle class="dot s{si % 8 + 1}" cx="{x:.1f}" cy="{y:.1f}" r="3.2"><title>{_e(labels[i])} · {_e(name)}: {_e(fmt_value(v, fmt))}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def _hbar(labels, series, fmt) -> str:
    n = len(labels)
    k = len(series)
    row_h = 14 * k + 10
    h = PAD_T + n * row_h + 30
    lw = min(200, max(60, max((len(lb) for lb in labels), default=4) * 7))
    vals = [v for _, s in series for v in s if v is not None]
    lo, hi, step = _nice(min(vals + [0]), max(vals + [0]))
    pw = W - lw - PAD_R - 10
    xv = lambda v: lw + 10 + (v - lo) / (hi - lo) * pw  # noqa: E731
    out = [f'<svg class="dt-svg" viewBox="0 0 {W} {h}" role="img" preserveAspectRatio="xMidYMid meet">']
    t = lo
    while t <= hi + step / 2:
        x = xv(t)
        out.append(f'<line class="grid{" zero" if abs(t) < 1e-12 else ""}" x1="{x:.1f}" x2="{x:.1f}" y1="{PAD_T}" y2="{h - 24}"/>')
        out.append(f'<text class="tick" x="{x:.1f}" y="{h - 8}" text-anchor="middle">{_e(_tick(t))}</text>')
        t += step
    for i, lb in enumerate(labels):
        y = PAD_T + i * row_h
        out.append(f'<text class="tick lbl" x="{lw}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end">{_e(_short(lb, 28))}<title>{_e(lb)}</title></text>')
        for si, (name, s) in enumerate(series):
            v = s[i]
            if v is None:
                continue
            x0, x1 = xv(0), xv(v)
            out.append(f'<rect class="s{si % 8 + 1}" x="{min(x0, x1):.1f}" y="{y + 5 + si * 14:.1f}" width="{max(abs(x1 - x0), .5):.1f}" height="12" rx="2">'
                       f'<title>{_e(lb)} · {_e(name)}: {_e(fmt_value(v, fmt))}</title></rect>')
    out.append("</svg>")
    return "".join(out)


def _pie(labels, values, donut, fmt) -> str:
    items = [(lb, v) for lb, v in zip(labels, values) if v is not None and v > 0]
    if not items:
        return ""
    items.sort(key=lambda x: -x[1])
    if len(items) > 8:
        rest = sum(v for _, v in items[7:])
        items = items[:7] + [("Altro", rest)]
    total = sum(v for _, v in items)
    cx, cy, r = 150, 150, 130
    out = [f'<svg class="dt-svg dt-pie" viewBox="0 0 {W} 300" role="img" preserveAspectRatio="xMidYMid meet">']
    a0 = -math.pi / 2
    for i, (lb, v) in enumerate(items):
        frac = v / total
        a1 = a0 + frac * 2 * math.pi
        tip = f"<title>{_e(lb)}: {_e(fmt_value(v, fmt))} ({fmt_number(frac * 100, 1)}%)</title>"
        if frac >= .9999:
            out.append(f'<circle class="s{i % 8 + 1}" cx="{cx}" cy="{cy}" r="{r}">{tip}</circle>')
        else:
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            large = 1 if frac > .5 else 0
            out.append(f'<path class="s{i % 8 + 1} slice" d="M{cx},{cy} L{x0:.2f},{y0:.2f} A{r},{r} 0 {large} 1 {x1:.2f},{y1:.2f} Z">{tip}</path>')
        a0 = a1
    if donut:
        out.append(f'<circle class="hole" cx="{cx}" cy="{cy}" r="{r * .58:.1f}"/>')
        out.append(f'<text class="pie-total" x="{cx}" y="{cy + 6}" text-anchor="middle">{_e(fmt_value(total, fmt) if fmt else _tick(total))}</text>')
    for i, (lb, v) in enumerate(items):
        y = 40 + i * 28
        out.append(f'<rect class="s{i % 8 + 1}" x="320" y="{y - 11}" width="14" height="14" rx="3"/>')
        out.append(f'<text class="legend" x="342" y="{y}">{_e(_short(lb, 30))} <tspan class="muted">· {_e(fmt_value(v, fmt))} · {fmt_number(v / total * 100, 1)}%</tspan></text>')
    out.append("</svg>")
    return "".join(out)
