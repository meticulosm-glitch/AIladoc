"""Tabelle dinamiche: ``/// table`` legge un Excel/CSV della documentazione (o i dati scritti
nel blocco) e lo trasforma: colonne calcolate, filtri, raggruppamenti, pivot, ordinamento,
totali, formati, evidenziazioni e grafici. Nel browser la tabella si ordina, si filtra e si
esporta in CSV.

Ordine delle operazioni: compute → filter → group/aggregate oppure pivot → sort → columns
→ limit → totals.
"""
from __future__ import annotations

import html
from typing import Any

from .. import storage
from . import Plugin, RenderCtx, color_attrs, doc_url
from .blockbase import RawStashBlock, blocks_extension, type_any, type_bool, type_text
from .charts import render_chart
from .tabledata import (MAX_OUT_ROWS, Expr, Table, TableError, aggregate, as_list, fmt_value, group_by,
                        load_file, load_inline, parse_agg_specs, pivot, select_columns, sort_rows, sort_value)

SHEET_EXT = ("xlsx", "xlsm", "csv", "tsv")


def _e(s: Any) -> str:
    return html.escape(str(s), quote=True)


class DataTable(RawStashBlock):
    NAME = "table"
    ARGUMENT = None
    ERROR_TITLE = "Tabella non valida"
    OPTIONS = {
        "source": ("", type_text), "sheet": ("", type_text), "header": ("1", type_text),
        "columns": (None, type_any), "compute": (None, type_any), "filter": ("", type_text),
        "group": (None, type_any), "aggregate": (None, type_any), "pivot": (None, type_any),
        "sort": (None, type_any), "limit": ("", type_text), "totals": (None, type_any),
        "format": (None, type_any), "highlight": ("", type_text), "highlight_color": ("", type_text),
        "colors": (None, type_any), "chart": ("", type_text), "x": ("", type_text), "y": (None, type_any),
        "chart_only": (False, type_bool), "chart_title": ("", type_text), "interactive": (True, type_bool),
        "search": (None, type_any), "caption": ("", type_text), "compact": (False, type_bool),
        "numbers": (False, type_bool),
    }

    def render(self, text: str) -> str:
        o = self.options
        src_info = ""
        if o["source"]:
            rel, _ = self.ctx.resolve(o["source"], kinds=("sheet",))
            if not rel.lower().endswith(SHEET_EXT):
                raise TableError("Il file deve essere .xlsx, .xlsm, .csv o .tsv.")
            header = int(o["header"]) if str(o["header"]).isdigit() and int(o["header"]) > 0 else 1
            table, sheet = load_file(storage.abs_path(rel), o["sheet"], header)
            name = storage.pretty(rel.rsplit("/", 1)[-1])
            sheet_txt = f" · foglio {sheet}" if rel.lower().endswith(("xlsx", "xlsm")) else ""
            src_info = (f'<a href="{_e(doc_url(rel))}" title="Apri il file sorgente">{_e(name)}</a>{_e(sheet_txt)}')
        else:
            table = load_inline(text)
        table = transform(table, o)
        fmts = {str(k): str(v) for k, v in (o["format"] or {}).items()} if isinstance(o["format"], dict) else {}
        fmts = {table.columns[table.index(k)]: v for k, v in fmts.items() if table.has(k)}
        chart = ""
        if o["chart"]:
            chart = render_chart(table, o["chart"], o["x"], as_list(o["y"]) if o["y"] else None,
                                 o["chart_title"], fmts, multi_default=bool(o["pivot"]))
        return render_html(table, o, fmts, chart, src_info, self.argument or o["caption"])


def transform(table: Table, o: dict) -> Table:
    # 1. colonne calcolate
    comp = o.get("compute")
    if comp:
        if isinstance(comp, str):
            items = []
            for part in comp.split(";"):
                if "=" not in part:
                    raise TableError("«compute» va scritto come Nome = espressione")
                k, v = part.split("=", 1)
                items.append((k.strip(), v.strip()))
        elif isinstance(comp, dict):
            items = [(str(k), str(v)) for k, v in comp.items()]
        else:
            raise TableError("«compute» deve essere una mappa Nome: espressione.")
        for name, src in items:
            ex = Expr(src, table)
            vals = [ex(r) for r in table.rows]
            if table.has(name):
                i = table.index(name)
                for r, v in zip(table.rows, vals):
                    r[i] = v
            else:
                table.columns.append(name)
                for r, v in zip(table.rows, vals):
                    while len(r) < len(table.columns) - 1:
                        r.append(None)
                    r.append(v)
    # 2. filtro
    if o.get("filter"):
        ex = Expr(o["filter"], table)
        table.rows = [r for r in table.rows if ex(r)]
    # 3. raggruppamento / pivot
    if o.get("pivot"):
        table = pivot(table, o["pivot"])
    elif o.get("group") or o.get("aggregate"):
        keys = as_list(o.get("group"))
        aggs = parse_agg_specs(o["aggregate"], table) if o.get("aggregate") else []
        if keys:
            table = group_by(table, keys, aggs)
        else:  # aggregazione senza gruppi: una sola riga di riepilogo
            row = []
            for func, col, _ in aggs:
                row.append(aggregate(func, table.col(col)) if col else len(table.rows))
            table = Table([a[2] for a in aggs], [row])
    # 4. ordinamento
    if o.get("sort"):
        sort_rows(table, o["sort"])
    # 5. colonne visibili / rinominate
    if o.get("columns"):
        table = select_columns(table, o["columns"])
    # 6. limite
    lim = str(o.get("limit") or "")
    if lim.isdigit():
        table.rows = table.rows[: int(lim)]
    table.rows = table.rows[:MAX_OUT_ROWS]
    return table


def _totals_row(table: Table, spec: Any) -> list[Any] | None:
    if spec in (None, False, "", "false", "no"):
        return None
    funcs: dict[int, str] = {}
    if spec is True or str(spec).lower() in ("true", "yes", "si", "sì", "1"):
        funcs = {i: "sum" for i in range(len(table.columns)) if table.is_numeric(i)}
    elif isinstance(spec, dict):
        funcs = {table.index(str(k)): str(v) for k, v in spec.items()}
    else:
        funcs = {table.index(c): "sum" for c in as_list(spec)}
    row: list[Any] = [None] * len(table.columns)
    for i, f in funcs.items():
        row[i] = aggregate(f, [r[i] if i < len(r) else None for r in table.rows])
    label_i = next((i for i in range(len(table.columns)) if i not in funcs), None)
    if label_i is not None:
        row[label_i] = "Totale"
    return row


def render_html(table: Table, o: dict, fmts: dict, chart: str, src_info: str, title: str) -> str:
    numeric = [table.is_numeric(i) for i in range(len(table.columns))]
    hl = Expr(o["highlight"], table) if o.get("highlight") else None
    hl_cls = color_attrs(o.get("highlight_color") or "yellow").get("class", "c-yellow")
    colors: dict[int, dict[str, str]] = {}
    if isinstance(o.get("colors"), dict):
        for col, mapping in o["colors"].items():
            if isinstance(mapping, dict):
                colors[table.index(str(col))] = {str(k).lower(): str(v) for k, v in mapping.items()}
    totals = _totals_row(table, o.get("totals"))
    interactive = o.get("interactive", True)
    n = len(table.rows)

    parts = [f'<figure class="dt{" dt-compact" if o.get("compact") else ""}"{" data-dt" if interactive else ""}>']
    head_bits = []
    if title:
        head_bits.append(f'<span class="dt-title">{_e(title)}</span>')
    if src_info:
        head_bits.append(f'<span class="dt-src">da {src_info}</span>')
    tools = ""
    if interactive and not o.get("chart_only"):
        show_search = o.get("search")
        show_search = (n > 8) if show_search is None else bool(show_search) and str(show_search).lower() not in ("false", "no")
        tools = '<span class="dt-tools">'
        if show_search:
            tools += '<input type="search" class="dt-search" placeholder="Filtra…" aria-label="Filtra le righe">'
        tools += '<button type="button" class="dt-btn" data-dt-export title="Scarica come CSV">CSV</button></span>'
    if head_bits or tools:
        parts.append(f'<figcaption class="dt-head"><span class="dt-meta">{"".join(head_bits)}</span>{tools}</figcaption>')
    if chart:
        parts.append(chart)
    if not o.get("chart_only"):
        parts.append('<div class="dt-scroll"><table class="dt-table"><thead><tr>')
        if o.get("numbers"):
            parts.append('<th class="dt-rn">#</th>')
        for i, c in enumerate(table.columns):
            cls = ' class="num"' if numeric[i] else ""
            parts.append(f'<th{cls} data-col="{i}" title="Ordina per {_e(c)}">{_e(c)}</th>')
        parts.append("</tr></thead><tbody>")
        for ri, r in enumerate(table.rows, start=1):
            rcls = f' class="dt-hl {hl_cls}"' if hl and hl(r) else ""
            parts.append(f"<tr{rcls}>")
            if o.get("numbers"):
                parts.append(f'<td class="dt-rn">{ri}</td>')
            for i in range(len(table.columns)):
                v = r[i] if i < len(r) else None
                txt = fmt_value(v, fmts.get(table.columns[i], ""))
                sv = sort_value(v)
                attrs = f' data-v="{_e(sv)}"' if sv else ""
                cls = ["num"] if numeric[i] else []
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
                    cls.append("neg")
                if i in colors and txt.lower() in colors[i]:
                    c = color_attrs(colors[i][txt.lower()]).get("class", "c-gray")
                    txt_html = f'<span class="aura-status aura-soft {c}">{_e(txt)}</span>'
                else:
                    txt_html = _e(txt)
                cls_attr = f' class="{" ".join(cls)}"' if cls else ""
                parts.append(f"<td{cls_attr}{attrs}>{txt_html}</td>")
            parts.append("</tr>")
        parts.append("</tbody>")
        if totals:
            parts.append('<tfoot><tr class="dt-total">')
            if o.get("numbers"):
                parts.append("<td></td>")
            for i, v in enumerate(totals):
                cls = ' class="num"' if numeric[i] else ""
                parts.append(f"<td{cls}>{_e(fmt_value(v, fmts.get(table.columns[i], '')))}</td>")
            parts.append("</tr></tfoot>")
        parts.append("</table></div>")
        note = f"{n} righe" if n != 1 else "1 riga"
        if table.truncated:
            note += " · il file è stato letto solo in parte (troppe righe)"
        parts.append(f'<div class="dt-foot"><span class="dt-count" data-total="{n}">{note}</span></div>')
    parts.append("</figure>")
    return "".join(parts)


def _extensions(ctx: RenderCtx) -> list:
    return [blocks_extension(DataTable)]


EX_INLINE = """/// table | Budget del reparto
    compute:
      Totale: Quantità * Prezzo
    sort: -Totale
    totals: [Quantità, Totale]
    format: {Prezzo: euro, Totale: euro}
    highlight: Totale > 1000
    colors: {Stato: {Approvato: green, In attesa: yellow, Respinto: red}}

| Voce        | Quantità | Prezzo | Stato      |
|-------------|---------:|-------:|------------|
| Portatili   | 4        | 950    | Approvato  |
| Monitor     | 6        | 189,90 | In attesa  |
| Licenze     | 10       | 49     | Approvato  |
| Formazione  | 2        | 600    | Respinto   |
///"""

EX_GROUP = """/// table | Spesa per categoria
    group: Categoria
    aggregate: ["sum(Importo) as Totale", "count(*) as Voci", "avg(Importo) as Media"]
    sort: -Totale
    format: {Totale: euro, Media: euro}
    chart: bar
    x: Categoria
    y: Totale

Categoria;Voce;Importo
Hardware;Portatili;3800
Hardware;Monitor;1139,40
Software;Licenze;490
Software;Antivirus;320
Servizi;Formazione;1200
///"""

EX_PIVOT = """/// table | Vendite per area e trimestre
    pivot: {rows: Area, columns: Trimestre, values: Vendite, agg: sum}
    totals: true
    chart: stacked
    x: Area

Area,Trimestre,Vendite
Nord,T1,120
Nord,T2,150
Centro,T1,80
Centro,T2,95
Sud,T1,60
Sud,T2,90
///"""

EX_FILE = """/// table | Prodotti sopra i 100 €
    source: /03-Commerciale/listino-2026.xlsx
    sheet: Listino
    filter: "[Prezzo €] >= 100"
    sort: -Prezzo €
    columns: [Prodotto, Categoria, Prezzo € as Prezzo]
    format: {Prezzo: euro}
///"""

EX_PIE = """/// table | Ripartizione ticket
    chart: donut
    chart_only: true

| Canale   | Ticket |
|----------|-------:|
| Email    | 340    |
| Telefono | 210    |
| Portale  | 520    |
| Chat     | 130    |
///"""

PLUGIN = Plugin(
    id="tables", name="Tabelle", icon="sheet",
    description=("Tabelle dinamiche da file Excel/CSV della documentazione o scritte nella pagina: colonne "
                 "calcolate, filtri, raggruppamenti, pivot, ordinamento, totali, formati (€, %), "
                 "evidenziazioni, stati colorati e grafici (barre, linee, aree, torta). Nel browser si "
                 "ordinano cliccando le intestazioni, si filtrano e si scaricano in CSV. Nell'editor: "
                 "tabelle visuali, incolla da Excel e tabelle collegate a un file."),
    extensions=_extensions,
    snippets=[
        {"label": "Tabella…", "icon": "▦", "action": "table-new"},
        {"label": "Modifica tabella (visuale)", "icon": "✏️", "action": "table-edit"},
        {"label": "Tabella da Excel/CSV…", "icon": "📗", "action": "table-source"},
        {"label": "Tabella calcolata", "icon": "🧮", "text": EX_INLINE},
        {"label": "Riepilogo per gruppo + grafico", "icon": "📊", "text": EX_GROUP},
        {"label": "Pivot", "icon": "🔀", "text": EX_PIVOT},
    ],
    examples=[
        ("Colonne calcolate, totali, formati e stati", EX_INLINE),
        ("Raggruppare e fare grafici", EX_GROUP), ("Pivot", EX_PIVOT), ("Solo grafico", EX_PIE),
        ("Dati da un file Excel o CSV", EX_FILE, False),
    ],
)
