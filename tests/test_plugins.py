"""Plugin: macro di formattazione, tabelle dinamiche, diagrammi draw.io."""
import base64
import urllib.parse
import zlib

import pytest
from conftest import csrf, login

from app.plugins import drawio
from app.plugins.tabledata import Expr, TableError, load_inline, parse_value
from app.plugins.tables import transform
from app.render import render_markdown

HR = "04-Risorse-Umane"
ALL = lambda _rel: True  # noqa: E731


def md(text, path="01-Guida/pagina.md", can_view=ALL):
    return render_markdown(text, path, can_view)[0]


# ------------------------------------------------------------------ macro
def test_pannello_card_pulsante_e_stato():
    h = md("/// panel | Titolo\n    color: green\n    icon: info\n\nTesto **forte**.\n///\n\n"
           "//// cards\n    columns: 2\n\n/// card | Uno\n    link: 01-primi-passi.md\n\nCorpo.\n///\n////\n\n"
           "/// button | Vai\n    link: index.md\n///\n\nStato {{status: Fatto | verde | solid}}")
    assert 'class="aura-panel aura-soft c-green"' in h and "<strong>forte</strong>" in h
    assert 'class="aura-cards cols-2 aura-elevated"' in h
    assert 'href="/d/01-Guida/01-primi-passi.md"' in h  # link relativi riscritti come nel resto della pagina
    assert 'class="aura-btn aura-solid size-md c-accent" href="/d/01-Guida/index.md"' in h
    assert '<span class="aura-status aura-solid c-green">Fatto</span>' in h


def test_colore_personalizzato_solo_esadecimale():
    assert 'style="--c:#123abc"' in md('/// panel | x\n    color: "#123abc"\n\nt\n///')
    h = md('/// panel | x\n    color: "red;background:url(x)"\n\nt\n///')
    assert "url(" not in h and "background" not in h


def test_link_javascript_bloccati():
    h = md("/// button | Clic\n    link: javascript:alert(1)\n///")
    assert "javascript:" not in h


def test_html_personalizzato_sanificato():
    h = md('/// html\n<p style="color:red; position:fixed" onclick="x()">ok</p><script>alert(1)</script>'
           '<iframe src="https://evil"></iframe>\n///')
    assert "ok" in h and "color:red" in h
    assert "script" not in h and "onclick" not in h and "position" not in h and "iframe" not in h


def test_embed_solo_siti_ammessi():
    h = md("/// embed | https://www.youtube.com/watch?v=abc123\n///")
    assert '<iframe src="https://www.youtube-nocookie.com/embed/abc123"' in h and "sandbox=" in h
    h = md("/// embed | https://evil.example.com/x\n///")
    assert "<iframe" not in h and "non è tra quelli ammessi" in h
    assert "<iframe" not in md("/// embed | http://www.youtube.com/watch?v=abc\n///")


def test_segnaposto_non_falsificabile():
    h = md("AILAPLUG00000000N0Z\n\n/// html\n<b>x</b>\n///")
    assert "AILAPLUG00000000N0Z" in h  # il testo dell'autore resta testo


def test_progress_countdown_latex():
    h = md("/// progress | 7/10\n    label: Lavori\n///\n\n/// countdown | 2099-01-01\n///\n\n$a^2$\n\n/// latex\nx^2\n///")
    assert 'style="width:70.0%"' in h and "7/10" in h
    assert 'data-countdown="2099-01-01T00:00:00"' in h
    assert 'class="arithmatex"' in h and "\\[x^2\\]" in h


def test_blocchi_senza_plugin_restano_testo(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "plugins", ["drawio"])
    h = md("/// panel | Titolo\n\nTesto\n///")
    assert "aura-panel" not in h


def test_include_rispetta_i_permessi(client, data_dir):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "restrict"})
    client.post("/edit/01-Guida/01-primi-passi.md", data={
        "csrf": token, "content": "# P\n\n/// include | ../04-Risorse-Umane/policy-ferie.md\n///\n\n"
                                  "/// include | 02-scrivere-in-markdown.md\n///\n\n/// pages | /\n///\n"})
    r = client.get("/d/01-Guida/01-primi-passi.md")
    assert "aura-include" in r.text and "Da</span>" in r.text
    ferie = (data_dir / "docs" / HR / "policy-ferie.md").read_text().strip().splitlines()[-1]
    login(client, "vera", "ailadoc-viewer")
    r = client.get("/d/01-Guida/01-primi-passi.md")
    assert r.status_code == 200
    assert "non esiste o non hai i permessi" in r.text
    assert ferie not in r.text
    assert "Risorse" not in r.text.split('class="aura-pages')[1].split("</div></div>")[0]


def test_include_circolare():
    from app.plugins import RefError, RenderCtx
    ctx = RenderCtx("a.md", ALL)
    with pytest.raises(RefError):
        ctx.child("a.md")


# ------------------------------------------------------------------ tabelle
def test_valori_italiani():
    assert parse_value("1.234,50") == 1234.5
    assert parse_value("€ 12,00") == 12
    assert parse_value("15%") == 0.15
    assert str(parse_value("31/12/2026")) == "2026-12-31"
    assert parse_value("A-100") == "A-100"


def test_tabella_calcoli_filtro_gruppo_totali():
    t = load_inline("Reparto;Voce;Q;Prezzo\nIT;PC;2;1.000\nIT;Monitor;3;200\nHR;Corso;1;500\nHR;Libri;10;20")
    o = {"compute": {"Totale": "Q * Prezzo"}, "filter": "Totale >= 200", "group": "Reparto",
         "aggregate": ["sum(Totale) as Spesa", "count(*) as N"], "sort": "-Spesa"}
    out = transform(t, o)
    assert out.columns == ["Reparto", "Spesa", "N"]
    assert out.rows == [["IT", 2600, 2], ["HR", 700, 2]]


def test_tabella_pivot_e_html():
    h = md("/// table | Vendite\n    pivot: {rows: Area, columns: T, values: V}\n    totals: true\n    chart: bar\n\n"
           "Area,T,V\nNord,T1,10\nNord,T2,5\nSud,T1,7\n///")
    assert "<svg" in h and 'class="dt-total"' in h and ">Vendite<" in h
    assert "<td>Totale</td>" in h and ">22<" in h


def test_espressioni_sicure():
    t = load_inline("A;B\n1;2")
    for bad in ("__import__('os').system('x')", "A.__class__", "(lambda: 1)()", "open('x')", "[x for x in A]"):
        with pytest.raises(TableError):
            Expr(bad, t)
    assert Expr("A = 1 AND B <> 3", t)(t.rows[0]) is True
    assert Expr("se(A > 0, 'pos', 'neg')", t)(t.rows[0]) == "pos"
    assert Expr("A / 0", t)(t.rows[0]) is None


def test_tabella_da_excel_e_permessi(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    page = ("# Listino\n\n/// table | Cari\n    source: /03-Commerciale/listino-2026.xlsx\n    sheet: Listino\n"
            "    filter: \"[Prezzo €] >= 100\"\n    sort: -Prezzo €\n    format: {Prezzo €: euro}\n///\n")
    client.post("/edit/01-Guida/01-primi-passi.md", data={"csrf": token, "content": page})
    r = client.get("/d/01-Guida/01-primi-passi.md")
    assert "Licenza piattaforma" in r.text and "€ 1.200,00" in r.text and "Sensore" not in r.text
    client.post("/admin/permissions", data={"csrf": token, "path": "03-Commerciale", "action": "restrict"})
    login(client, "vera", "ailadoc-viewer")
    r = client.get("/d/01-Guida/01-primi-passi.md")
    assert "Licenza piattaforma" not in r.text and "non hai i permessi" in r.text


def test_tabella_errori_leggibili():
    assert 'class="plug-unparsed"' in md("/// table\n    filter: [A] > 1\n\nA\n1\n///")
    assert "Colonna «Nessuna» non trovata" in md("/// table\n    sort: Nessuna\n\nA,B\n1,2\n///")
    assert "Percorso non valido" in md("/// table\n    source: ../../etc/passwd\n///")


# ------------------------------------------------------------------ draw.io
def _compressed(model: str) -> str:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = c.compress(urllib.parse.quote(model).encode()) + c.flush()
    return base64.b64encode(data).decode()


MODEL = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
         '<mxCell id="2" value="Server &lt;b&gt;principale&lt;/b&gt;" vertex="1" parent="1"/>'
         '<UserObject label="Router di confine" id="3"><mxCell vertex="1" parent="1"/></UserObject></root></mxGraphModel>')
DIAGRAM = (f'<mxfile><diagram name="Rete">{_compressed(MODEL)}</diagram>'
           f'<diagram name="Flusso"><mxGraphModel><root><mxCell id="0"/><mxCell id="9" value="Approvazione"/>'
           f'</root></mxGraphModel></diagram></mxfile>')


def test_drawio_formato_compresso_e_testo():
    pts = drawio.page_texts(DIAGRAM)
    assert pts[0] == ("Rete", ["Server principale", "Router di confine"])
    assert pts[1] == ("Flusso", ["Approvazione"])
    with pytest.raises(drawio.DiagramError):
        drawio.validate('<!DOCTYPE x [<!ENTITY a "b">]><mxfile/>')
    with pytest.raises(drawio.DiagramError):
        drawio.validate("<html/>")


def test_drawio_pagina_file_incorporamento_e_assistente(client, data_dir):
    (data_dir / "docs/02-Procedure/rete.drawio").write_text(DIAGRAM)
    login(client, "editor", "ailadoc-editor")
    r = client.get("/d/02-Procedure/rete.drawio")
    assert r.status_code == 200 and 'class="mxgraph"' in r.text and "Modifica diagramma" in r.text
    token = csrf(client)
    client.post("/edit/02-Procedure/gestione-resi.md", data={
        "csrf": token, "content": "# Resi\n\n![Rete](rete.drawio)\n\n/// drawio | rete.drawio\n    page: Flusso\n///\n"})
    r = client.get("/d/02-Procedure/gestione-resi.md")
    assert r.text.count('class="mxgraph"') == 2 and "&quot;page&quot;: 1" in r.text
    r = client.post("/api/assistant", json={"question": "router di confine"}, headers={"X-CSRF-Token": token})
    assert any(s["path"] == "02-Procedure/rete.drawio" for s in r.json()["sources"])


def test_drawio_salva_e_crea(client, data_dir):
    (data_dir / "docs/02-Procedure/rete.drawio").write_text(DIAGRAM)
    login(client, "viewer", "ailadoc-viewer")
    token = csrf(client)
    h = {"X-CSRF-Token": token}
    assert client.post("/api/drawio/save", json={"path": "02-Procedure/rete.drawio", "xml": "<mxfile/>"},
                       headers=h).status_code == 403
    assert "Modifica diagramma" not in client.get("/d/02-Procedure/rete.drawio").text
    login(client, "editor", "ailadoc-editor")
    h = {"X-CSRF-Token": csrf(client)}
    assert client.post("/api/drawio/save", json={"path": "02-Procedure/rete.drawio", "xml": "<html/>"},
                       headers=h).status_code == 400
    assert client.post("/api/drawio/save", json={"path": "02-Procedure/gestione-resi.md", "xml": "<mxfile/>"},
                       headers=h).status_code == 404
    r = client.post("/api/drawio/save", json={"path": "02-Procedure/rete.drawio", "xml": drawio.EMPTY}, headers=h)
    assert r.status_code == 200 and (data_dir / "docs/02-Procedure/rete.drawio").read_text() == drawio.EMPTY
    r = client.post("/api/drawio/new", json={"folder": "02-Procedure", "name": "Flusso ordini"}, headers=h)
    assert r.json()["path"] == "02-Procedure/flusso-ordini.drawio"
    assert client.post("/api/drawio/new", json={"folder": "02-Procedure", "name": "flusso-ordini.drawio"},
                       headers=h).status_code == 409
    assert client.post("/api/drawio/save", json={"path": "02-Procedure/rete.drawio", "xml": drawio.EMPTY}).status_code == 403


def test_guida_ed_editor(client):
    login(client, "viewer", "ailadoc-viewer")
    r = client.get("/plugins")
    assert r.status_code == 200 and "Tabelle" in r.text and "aura-cards" in r.text and "dt-table" in r.text
    login(client, "editor", "ailadoc-editor")
    r = client.get("/edit/01-Guida/01-primi-passi.md")
    assert 'id="plugin-data"' in r.text and "03-Commerciale/listino-2026.xlsx" in r.text
    token = csrf(client)
    r = client.post("/api/render", json={"content": "---\nnumbered_headings: true\n---\n/// panel\n\nx\n///",
                                         "path": "01-Guida/x.md"}, headers={"X-CSRF-Token": token})
    assert r.json()["numbered"] is True and "aura-panel" in r.json()["html"]
