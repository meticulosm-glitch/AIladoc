"""Diagrammi draw.io (diagrams.net).

- I file ``.drawio`` / ``.dio`` nella documentazione si aprono con il visualizzatore draw.io
  (pagine, livelli, zoom, schermo intero) e chi può modificarli li apre nell'editor draw.io
  incorporato: il diagramma viaggia via postMessage tra la pagina e l'iframe, non passa dai
  server di draw.io, e viene salvato da AIladoc nel file originale.
- Nelle pagine: ``/// drawio | schema-rete.drawio`` oppure ``![Schema](schema-rete.drawio)``.
- Il testo delle forme viene indicizzato: AIla trova e cita i diagrammi (con la pagina giusta).
"""
from __future__ import annotations

import base64
import html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from .. import storage
from ..config import settings
from . import Plugin, RefError, RenderCtx, doc_url, error_box
from .blockbase import RawStashBlock, blocks_extension, type_bool, type_text

EXTS = ("drawio", "dio")
MAX_BYTES = 15 * 1024 * 1024
EMPTY = ('<mxfile host="AIladoc"><diagram id="pagina-1" name="Pagina-1"><mxGraphModel dx="1000" dy="600" grid="1" '
         'gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
         'pageWidth="1169" pageHeight="827" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
         '</root></mxGraphModel></diagram></mxfile>')


class DiagramError(ValueError):
    pass


def is_diagram(name: str) -> bool:
    return name.lower().rsplit(".", 1)[-1] in EXTS


# --------------------------------------------------------------------------- formato
def _inflate(text: str) -> str:
    """Contenuto compresso di <diagram>: base64 → deflate "raw" → URL-encoding."""
    data = base64.b64decode(text.strip())
    raw = zlib.decompressobj(-15).decompress(data, MAX_BYTES * 4)
    return urllib.parse.unquote(raw.decode("utf-8", errors="replace"))


def _parse_xml(text: str) -> ET.Element:
    if "<!DOCTYPE" in text[:2000] or "<!ENTITY" in text[:5000]:
        raise DiagramError("Il file contiene una DTD: non ammesso.")
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise DiagramError(f"XML non valido: {e}") from e


def validate(xml: str) -> None:
    """Controlla che il testo sia un diagramma draw.io (usato al salvataggio dall'editor)."""
    if len(xml.encode("utf-8")) > MAX_BYTES:
        raise DiagramError("Diagramma troppo grande.")
    root = _parse_xml(xml)
    if root.tag not in ("mxfile", "mxGraphModel"):
        raise DiagramError("Non è un diagramma draw.io.")


def pages(xml: str) -> list[dict]:
    """[{name, model (Element mxGraphModel o None)}] per ogni pagina del diagramma."""
    root = _parse_xml(xml)
    if root.tag == "mxGraphModel":
        return [{"name": "Pagina 1", "model": root}]
    if root.tag != "mxfile":
        raise DiagramError("Non è un diagramma draw.io.")
    out = []
    for i, d in enumerate(root.findall("diagram"), start=1):
        model = d.find("mxGraphModel")
        if model is None and (d.text or "").strip():
            try:
                model = _parse_xml(_inflate(d.text))
            except (ValueError, zlib.error, DiagramError):
                model = None
        out.append({"name": d.get("name") or f"Pagina {i}", "model": model})
    return out


_TAG = re.compile(r"<[^>]+>")


def _label(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</(div|p|li)>", "\n", s or "", flags=re.I)
    s = html.unescape(_TAG.sub(" ", s))
    return re.sub(r"[ \t]+", " ", s).strip()


def page_texts(xml: str) -> list[tuple[str, list[str]]]:
    """[(nome pagina, [testi delle forme])]"""
    out = []
    for pg in pages(xml):
        texts: list[str] = []
        model = pg["model"]
        if model is not None:
            for el in model.iter():
                if el.tag == "mxCell":
                    v = _label(el.get("value", ""))
                    if v:
                        texts.append(v)
                elif el.tag in ("UserObject", "object"):
                    for k, v in el.attrib.items():
                        if k in ("id", "placeholders") or not v:
                            continue
                        t = _label(v)
                        if t:
                            texts.append(t)
        out.append((pg["name"], texts))
    return out


def extract(p: Path) -> list[tuple[str, str, str]]:
    """Per l'assistente: [(posizione, ancora, testo)] — una voce per pagina del diagramma."""
    if p.stat().st_size > MAX_BYTES:
        return []
    xml = p.read_text(encoding="utf-8", errors="replace")
    pts = page_texts(xml)
    multi = len(pts) > 1
    out = []
    for i, (name, texts) in enumerate(pts, start=1):
        if not texts:
            continue
        loc = f"Pagina {name}" if multi else ""
        anchor = f"?page={i}" if multi else ""
        body = "Diagramma: " + " · ".join(dict.fromkeys(texts))
        while body:
            out.append((loc, anchor, body[:900]))
            body = body[900:]
    return out


def read_diagram(p: Path) -> str:
    if p.stat().st_size > MAX_BYTES:
        raise DiagramError("Diagramma troppo grande da visualizzare.")
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return EMPTY
    validate(text)
    return text


def page_index(xml: str, page: str) -> int:
    page = (page or "").strip()
    if not page:
        return 0
    if page.isdigit():
        return max(0, int(page) - 1)
    for i, pg in enumerate(pages(xml)):
        if pg["name"].lower() == page.lower():
            return i
    raise DiagramError(f"Pagina «{page}» non trovata nel diagramma.")


# --------------------------------------------------------------------------- HTML
def viewer_html(rel: str, xml: str, *, page: int = 0, height: str = "", toolbar: bool = True,
                lightbox: bool = True, caption: str = "", full: bool = False, zoom: str = "") -> str:
    cfg = {
        "xml": xml, "page": page, "highlight": "#0d6e5c", "nav": True, "resize": not height,
        "toolbar": "pages zoom layers tags lightbox" if toolbar else "", "toolbar-nohide": full,
        "lightbox": lightbox, "border": 12, "center": True, "target": "self",
    }
    if zoom:
        try:
            cfg["zoom"] = max(.1, min(4.0, float(zoom.replace(",", "."))))
        except ValueError:
            pass
    style = ""
    if height.isdigit():
        style = f' style="height:{min(int(height), 3000)}px"'
    name = storage.pretty(rel.rsplit("/", 1)[-1]) if rel else "Diagramma"
    cap = ""
    if not full:
        cap = (f'<figcaption><span>{html.escape(caption or name)}</span>'
               f'<a href="{html.escape(doc_url(rel))}" title="Apri il diagramma">Apri ↗</a></figcaption>')
    return (f'<figure class="drawio{" drawio-full" if full else ""}" data-drawio data-path="{html.escape(rel)}">'
            f'<div class="drawio-frame"{style}><div class="mxgraph" data-mxgraph="{html.escape(json.dumps(cfg))}">'
            f'</div><noscript>Serve JavaScript per vedere il diagramma.</noscript></div>{cap}</figure>')


def embed(ctx: RenderCtx, ref: str, opts: dict) -> str:
    rel, frag = ctx.resolve(ref, kinds=("diagram",))
    xml = read_diagram(storage.abs_path(rel))
    page = page_index(xml, opts.get("page") or (frag[5:] if frag.startswith("page=") else ""))
    return viewer_html(rel, xml, page=page, height=opts.get("height", ""), toolbar=opts.get("toolbar", True),
                       lightbox=opts.get("lightbox", True), caption=opts.get("caption", ""),
                       zoom=opts.get("zoom", ""))


class DrawioBlock(RawStashBlock):
    NAME = "drawio"
    ARGUMENT = True
    ERROR_TITLE = "Diagramma non disponibile"
    OPTIONS = {"page": ("", type_text), "height": ("", type_text), "zoom": ("", type_text),
               "toolbar": (True, type_bool), "lightbox": (True, type_bool), "caption": ("", type_text)}

    def render(self, text):
        try:
            return embed(self.ctx, self.argument, self.options)
        except DiagramError as e:
            raise ValueError(str(e)) from e


class _ImageDiagrams(Treeprocessor):
    """``![didascalia](schema.drawio)`` → visualizzatore (prima che i link diventino /raw/...)."""

    def run(self, root):
        ctx: RenderCtx = self.md.ailadoc_ctx
        for parent in root.iter():
            for i, el in enumerate(list(parent)):
                if el.tag != "img":
                    continue
                src = el.get("src", "")
                path = urllib.parse.urlsplit(src).path
                if not is_diagram(path) or urllib.parse.urlsplit(src).scheme:
                    continue
                try:
                    out = embed(ctx, src, {"caption": el.get("alt", "")})
                except (RefError, DiagramError) as e:
                    out = error_box(str(e), "Diagramma non disponibile")
                token = ctx.put(out)
                if parent.tag == "p" and len(parent) == 1 and not (parent.text or "").strip() \
                        and not (el.tail or "").strip():
                    parent.remove(el)  # immagine da sola nel paragrafo: il paragrafo diventa il segnaposto
                    parent.tag, parent.text = "div", token
                    parent.attrib.clear()
                    parent.set("class", "ailaplug-slot")
                    continue
                slot = el.makeelement("span", {"class": "ailaplug-slot"})
                slot.text = token
                slot.tail = el.tail
                parent.remove(el)
                parent.insert(i, slot)


class _ImgExt(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(_ImageDiagrams(md), "ailadoc_drawio_img", 6)


def _extensions(ctx: RenderCtx) -> list:
    return [blocks_extension(DrawioBlock), _ImgExt()]


def editor_url() -> str:
    base = settings.drawio_editor_url
    if not base:
        return ""
    q = "embed=1&proto=json&spin=1&ui=atlas&lang=it&saveAndExit=1&noSaveBtn=0&libraries=1&configure=0"
    return f"{base}/?{q}"


EX_EMBED = """/// drawio | schema-rete.drawio
    page: 1
    height: 420
    caption: Schema della rete di sede
///

Oppure, più semplice: `![Schema della rete](schema-rete.drawio)`"""

PLUGIN = Plugin(
    id="drawio", name="Diagrammi draw.io", icon="diagram",
    description=("I file .drawio si aprono con il visualizzatore draw.io (pagine, livelli, zoom, schermo "
                 "intero) e si modificano nel browser con l'editor draw.io: il diagramma resta nella "
                 "documentazione. Si incorporano nelle pagine e AIla ne cita il contenuto."),
    extensions=_extensions,
    snippets=[
        {"label": "Nuovo diagramma…", "icon": "✳️", "action": "drawio-new"},
        {"label": "Diagramma esistente…", "icon": "🧭", "action": "drawio-insert"},
    ],
    examples=[("Incorporare un diagramma", EX_EMBED, False)],
)
