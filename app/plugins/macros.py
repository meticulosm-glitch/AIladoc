"""Macro di formattazione (stile «Aura» per Confluence) scritte in Markdown.

Sintassi a blocchi di pymdownx (compatibile MkDocs Material)::

    /// panel | Titolo
        color: blue
        icon: info

    Contenuto **Markdown**.
    ///

Per annidare un blocco dentro un altro, il contenitore usa più barre (``////`` fuori, ``///`` dentro).
"""
from __future__ import annotations

import datetime as dt
import html
import posixpath
import re
import xml.etree.ElementTree as etree
from urllib.parse import parse_qs, quote, urlsplit

from markdown.extensions.toc import slugify
from markdown.inlinepatterns import InlineProcessor
from markdown.util import AtomicString
from markdown.extensions import Extension
from pymdownx.blocks.block import type_boolean

from .. import storage
from ..config import settings
from . import Plugin, RefError, RenderCtx, color_attrs, doc_url, merge_class
from .blockbase import CtxBlock, RawStashBlock, blocks_extension, type_bool, type_text

# ------------------------------------------------------------------- icone
ICONS = {
    "info": "ℹ️", "note": "📝", "nota": "📝", "warning": "⚠️", "attenzione": "⚠️", "danger": "⛔", "stop": "⛔",
    "check": "✅", "ok": "✅", "done": "✅", "x": "❌", "no": "❌", "idea": "💡", "tip": "💡", "rocket": "🚀",
    "star": "⭐", "doc": "📄", "docs": "📄", "book": "📘", "guide": "📘", "link": "🔗", "user": "👤",
    "team": "👥", "users": "👥", "calendar": "📅", "clock": "⏰", "time": "⏱️", "lock": "🔒", "key": "🔑",
    "gear": "⚙️", "settings": "⚙️", "chart": "📊", "stats": "📈", "mail": "✉️", "email": "✉️",
    "phone": "📞", "money": "💶", "euro": "💶", "flag": "🚩", "heart": "❤️", "question": "❓", "help": "❓",
    "tools": "🛠️", "cloud": "☁️", "database": "🗄️", "db": "🗄️", "bug": "🐞", "fire": "🔥", "bell": "🔔",
    "pin": "📌", "home": "🏠", "search": "🔍", "folder": "📁", "download": "⬇️", "upload": "⬆️",
    "shield": "🛡️", "security": "🛡️", "server": "🖥️", "laptop": "💻", "mobile": "📱", "truck": "🚚",
    "cart": "🛒", "package": "📦", "target": "🎯", "trophy": "🏆", "megaphone": "📣", "news": "📰",
    "map": "🗺️", "location": "📍", "support": "🛟", "training": "🎓", "legal": "⚖️", "factory": "🏭",
    "leaf": "🌿", "light": "💡", "puzzle": "🧩", "diagram": "🧭", "table": "📋", "clipboard": "📋",
}


def icon_text(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    return ICONS.get(name.lower(), name[:4])


def _icon(parent: etree.Element, name: str, cls: str = "aura-icon") -> None:
    t = icon_text(name)
    if t:
        etree.SubElement(parent, "span", {"class": cls, "aria-hidden": "true"}).text = t


def _choice(*values: str):
    def parse(v):
        v = type_text(v).lower()
        if v and v not in values:
            raise ValueError(v)
        return v
    return parse


# ------------------------------------------------------------------- struttura
class Panel(CtxBlock):
    NAME = "panel"
    ARGUMENT = None
    OPTIONS = {"color": ("", type_text), "icon": ("", type_text),
               "style": ("", _choice("soft", "solid", "outline", "left"))}

    def on_create(self, parent):
        attrs = merge_class(color_attrs(self.options["color"], "blue"), "aura-panel",
                            f"aura-{self.options['style'] or 'soft'}")
        el = etree.SubElement(parent, "div", attrs)
        if self.argument or self.options["icon"]:
            t = etree.SubElement(el, "div", {"class": "aura-panel-title"})
            _icon(t, self.options["icon"])
            if self.argument:
                etree.SubElement(t, "span").text = self.argument
        etree.SubElement(el, "div", {"class": "aura-panel-body"})
        return el

    def on_add(self, block):
        return block[-1]


class Expand(CtxBlock):
    NAME = "expand"
    ARGUMENT = None
    OPTIONS = {"open": (False, type_boolean), "color": ("", type_text), "icon": ("", type_text)}

    def on_create(self, parent):
        attrs = merge_class(color_attrs(self.options["color"]), "aura-expand")
        if self.options["open"]:
            attrs["open"] = "open"
        el = etree.SubElement(parent, "details", attrs)
        s = etree.SubElement(el, "summary")
        _icon(s, self.options["icon"])
        etree.SubElement(s, "span").text = self.argument or "Mostra dettagli"
        etree.SubElement(el, "div", {"class": "aura-expand-body"})
        return el

    def on_add(self, block):
        return block[-1]


class Tabs(CtxBlock):
    """Contenitore per ``/// tab``: orientamento verticale o stile a pillole."""
    NAME = "tabs"
    ARGUMENT = None
    OPTIONS = {"style": ("", _choice("vertical", "verticale", "pills", "pillole", "boxed")),
               "color": ("", type_text)}

    def on_create(self, parent):
        style = {"verticale": "vertical", "pillole": "pills"}.get(self.options["style"], self.options["style"])
        attrs = merge_class(color_attrs(self.options["color"]), "aura-tabs", f"aura-tabs-{style}" if style else "")
        return etree.SubElement(parent, "div", attrs)


_WIDTHS = {"1/4": "25", "25%": "25", "1/3": "33", "33%": "33", "1/2": "50", "50%": "50", "2/3": "66",
           "66%": "66", "67%": "66", "3/4": "75", "75%": "75", "20%": "20", "40%": "40", "60%": "60", "80%": "80"}


class Columns(CtxBlock):
    NAME = "columns"
    ARGUMENT = False
    OPTIONS = {"gap": ("", _choice("sm", "md", "lg", "none")), "align": ("", _choice("top", "center", "bottom"))}

    def on_create(self, parent):
        cls = ["aura-columns"]
        if self.options["gap"]:
            cls.append(f"gap-{self.options['gap']}")
        if self.options["align"]:
            cls.append(f"align-{self.options['align']}")
        return etree.SubElement(parent, "div", {"class": " ".join(cls)})


class Column(CtxBlock):
    NAME = "column"
    ARGUMENT = None
    OPTIONS = {"width": ("", type_text), "color": ("", type_text)}

    def on_create(self, parent):
        w = (self.argument or self.options["width"]).replace(" ", "")
        cls = ["aura-column"]
        if w in _WIDTHS:
            cls.append(f"w-{_WIDTHS[w]}")
        elif w.isdigit() and 1 <= int(w) <= 4:
            cls.append(f"grow-{w}")
        attrs = color_attrs(self.options["color"])
        if attrs:
            cls.append("aura-tinted")
        return etree.SubElement(parent, "div", merge_class(attrs, *cls))


class Background(CtxBlock):
    NAME = "background"
    ARGUMENT = None
    OPTIONS = {"color": ("", type_text), "style": ("", _choice("soft", "solid", "gradient", "outline")),
               "padding": ("", _choice("sm", "md", "lg"))}

    def on_create(self, parent):
        attrs = merge_class(color_attrs(self.argument or self.options["color"], "gray"), "aura-background",
                            f"aura-{self.options['style'] or 'soft'}", f"pad-{self.options['padding'] or 'md'}")
        return etree.SubElement(parent, "div", attrs)


class Divider(CtxBlock):
    NAME = "divider"
    ARGUMENT = None
    OPTIONS = {"style": ("", _choice("solid", "dashed", "dotted", "double", "gradient")),
               "color": ("", type_text), "icon": ("", type_text), "align": ("", _choice("left", "center", "right"))}

    def on_create(self, parent):
        attrs = merge_class(color_attrs(self.options["color"]), "aura-divider",
                            f"line-{self.options['style'] or 'solid'}", f"align-{self.options['align'] or 'center'}")
        el = etree.SubElement(parent, "div", {**attrs, "role": "separator"})
        if self.argument or self.options["icon"]:
            lab = etree.SubElement(el, "span", {"class": "aura-divider-label"})
            _icon(lab, self.options["icon"])
            if self.argument:
                etree.SubElement(lab, "span").text = self.argument
        else:
            el.set("class", el.get("class") + " plain")
        return el

    def on_add(self, block):  # il divisore non ha contenuto
        return etree.Element("div")


# ------------------------------------------------------------------- visivi
class Title(CtxBlock):
    NAME = "title"
    ARGUMENT = True
    OPTIONS = {"subtitle": ("", type_text), "color": ("", type_text), "icon": ("", type_text),
               "level": ("2", _choice("1", "2", "3", "4")), "align": ("", _choice("left", "center", "right")),
               "style": ("", _choice("plain", "underline", "band", "bar"))}

    def on_create(self, parent):
        attrs = merge_class(color_attrs(self.options["color"]), "aura-title",
                            f"aura-title-{self.options['style'] or 'plain'}", f"align-{self.options['align'] or 'left'}")
        wrap = etree.SubElement(parent, "div", attrs)
        h = etree.SubElement(wrap, f"h{self.options['level'] or '2'}")
        if self.options["icon"]:
            h.text = icon_text(self.options["icon"]) + " "
        tail = etree.SubElement(h, "span")
        tail.text = self.argument
        if self.options["subtitle"]:
            etree.SubElement(wrap, "p", {"class": "aura-subtitle"}).text = self.options["subtitle"]
        return wrap

    def on_add(self, block):
        return etree.Element("div")


class Hero(CtxBlock):
    NAME = "hero"
    ARGUMENT = None
    OPTIONS = {"subtitle": ("", type_text), "color": ("", type_text), "image": ("", type_text),
               "align": ("", _choice("left", "center")), "style": ("", _choice("gradient", "solid", "soft", "image")),
               "icon": ("", type_text)}

    def on_create(self, parent):
        style = self.options["style"] or ("image" if self.options["image"] else "gradient")
        attrs = merge_class(color_attrs(self.options["color"], "accent"), "aura-hero", f"aura-{style}",
                            f"align-{self.options['align'] or 'left'}")
        el = etree.SubElement(parent, "section", attrs)
        if self.options["image"]:
            etree.SubElement(el, "img", {"class": "aura-hero-img", "src": self.options["image"], "alt": ""})
        inner = etree.SubElement(el, "div", {"class": "aura-hero-inner"})
        _icon(inner, self.options["icon"], "aura-hero-icon")
        if self.argument:
            etree.SubElement(inner, "div", {"class": "aura-hero-title"}).text = self.argument
        if self.options["subtitle"]:
            etree.SubElement(inner, "p", {"class": "aura-hero-sub"}).text = self.options["subtitle"]
        etree.SubElement(inner, "div", {"class": "aura-hero-body"})
        return el

    def on_add(self, block):
        return block.find("./div[@class='aura-hero-inner']/div[@class='aura-hero-body']")


class Cards(CtxBlock):
    NAME = "cards"
    ARGUMENT = None
    OPTIONS = {"columns": ("", _choice("1", "2", "3", "4", "5", "6")),
               "style": ("", _choice("elevated", "outline", "flat", "tinted")), "color": ("", type_text)}

    def on_create(self, parent):
        cols = self.argument if (self.argument or "") in ("1", "2", "3", "4", "5", "6") else self.options["columns"]
        attrs = merge_class(color_attrs(self.options["color"]), "aura-cards",
                            f"cols-{cols}" if cols else "cols-auto", f"aura-{self.options['style'] or 'elevated'}")
        return etree.SubElement(parent, "div", attrs)


class Card(CtxBlock):
    NAME = "card"
    ARGUMENT = None
    OPTIONS = {"icon": ("", type_text), "link": ("", type_text), "color": ("", type_text),
               "image": ("", type_text), "badge": ("", type_text), "footer": ("", type_text)}

    def on_create(self, parent):
        link = self.options["link"]
        attrs = merge_class(color_attrs(self.options["color"]), "aura-card", "has-link" if link else "")
        el = etree.SubElement(parent, "div", attrs)
        if self.options["image"]:
            etree.SubElement(el, "img", {"class": "aura-card-img", "src": self.options["image"], "alt": "",
                                         "loading": "lazy"})
        head = etree.SubElement(el, "div", {"class": "aura-card-head"})
        _icon(head, self.options["icon"], "aura-card-icon")
        if self.argument:
            if link:
                a = etree.SubElement(head, "a", {"class": "aura-card-title aura-stretched", "href": link})
                a.text = self.argument
            else:
                etree.SubElement(head, "div", {"class": "aura-card-title"}).text = self.argument
        if self.options["badge"]:
            etree.SubElement(head, "span", {"class": "aura-status"}).text = self.options["badge"]
        etree.SubElement(el, "div", {"class": "aura-card-body"})
        if self.options["footer"]:
            etree.SubElement(el, "div", {"class": "aura-card-foot"}).text = self.options["footer"]
        return el

    def on_add(self, block):
        return block.find("./div[@class='aura-card-body']")


class Button(CtxBlock):
    NAME = "button"
    ARGUMENT = True
    OPTIONS = {"link": ("", type_text), "color": ("", type_text), "icon": ("", type_text),
               "style": ("", _choice("solid", "outline", "ghost", "soft")),
               "size": ("", _choice("sm", "md", "lg")), "new_tab": (False, type_bool),
               "align": ("", _choice("left", "center", "right"))}

    def on_create(self, parent):
        wrap = etree.SubElement(parent, "div", {"class": f"aura-btn-wrap align-{self.options['align'] or 'left'}"})
        attrs = merge_class(color_attrs(self.options["color"], "accent"), "aura-btn",
                            f"aura-{self.options['style'] or 'solid'}", f"size-{self.options['size'] or 'md'}")
        attrs["href"] = self.options["link"] or "#"
        if self.options["new_tab"]:
            attrs["target"] = "_blank"
        a = etree.SubElement(wrap, "a", attrs)
        _icon(a, self.options["icon"], "aura-btn-icon")
        etree.SubElement(a, "span").text = self.argument
        return wrap

    def on_add(self, block):
        return etree.Element("div")


# ------------------------------------------------------------------- dati
def _num(v: str) -> float:
    return float(v.replace("%", "").replace(",", ".").strip())


class Progress(CtxBlock):
    NAME = "progress"
    ARGUMENT = True
    OPTIONS = {"label": ("", type_text), "color": ("", type_text), "max": ("100", type_text),
               "size": ("", _choice("sm", "md", "lg")), "show_value": (True, type_bool)}

    def on_validate(self, parent):
        arg = (self.argument or "").strip()
        try:
            if "/" in arg:
                a, b = arg.split("/", 1)
                val, mx = _num(a), _num(b)
            else:
                val, mx = _num(arg), _num(self.options["max"] or "100")
        except ValueError:
            return False
        self.pct = max(0.0, min(100.0, (val / mx * 100) if mx else 0.0))
        self.text = arg if "/" in arg else f"{round(self.pct)}%"
        return True

    def on_create(self, parent):
        color = self.options["color"] or ("green" if self.pct >= 100 else "")
        attrs = merge_class(color_attrs(color, "accent"), "aura-progress", f"size-{self.options['size'] or 'md'}")
        el = etree.SubElement(parent, "div", attrs)
        if self.options["label"] or self.options["show_value"]:
            head = etree.SubElement(el, "div", {"class": "aura-progress-head"})
            etree.SubElement(head, "span").text = self.options["label"]
            if self.options["show_value"]:
                etree.SubElement(head, "span", {"class": "aura-progress-val"}).text = AtomicString(self.text)
        track = etree.SubElement(el, "div", {"class": "aura-progress-track", "role": "progressbar",
                                             "aria-valuenow": str(round(self.pct)), "aria-valuemin": "0",
                                             "aria-valuemax": "100"})
        etree.SubElement(track, "div", {"class": "aura-progress-bar", "style": f"width: {self.pct:.1f}%"})
        return el

    def on_add(self, block):
        return etree.Element("div")


_DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y")
_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
           "ottobre", "novembre", "dicembre"]


def parse_date(s: str) -> dt.datetime:
    s = s.strip()
    for f in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            continue
    raise ValueError(f"data non riconosciuta: {s}")


def it_date(d: dt.datetime) -> str:
    out = f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
    return out + (f", ore {d:%H:%M}" if (d.hour or d.minute) else "")


class Countdown(CtxBlock):
    NAME = "countdown"
    ARGUMENT = True
    OPTIONS = {"label": ("", type_text), "done": ("", type_text), "color": ("", type_text),
               "style": ("", _choice("boxes", "inline"))}

    def on_validate(self, parent):
        try:
            self.when = parse_date(self.argument)
        except ValueError:
            return False
        return True

    def on_create(self, parent):
        attrs = merge_class(color_attrs(self.options["color"], "accent"), "aura-countdown",
                            f"aura-cd-{self.options['style'] or 'boxes'}")
        el = etree.SubElement(parent, "div", attrs)
        if self.options["label"]:
            etree.SubElement(el, "div", {"class": "aura-countdown-label"}).text = self.options["label"]
        days = (self.when.date() - dt.date.today()).days
        fallback = (f"{it_date(self.when)} · tra {days} giorni" if days > 0
                    else (self.options["done"] or f"{it_date(self.when)}"))
        etree.SubElement(el, "div", {"class": "aura-countdown-time", "data-countdown": self.when.isoformat(),
                                     "data-done": self.options["done"] or "Scaduto"}).text = fallback
        etree.SubElement(el, "div", {"class": "aura-countdown-date"}).text = it_date(self.when)
        return el

    def on_add(self, block):
        return etree.Element("div")


# ------------------------------------------------------------------- avanzate
class Latex(RawStashBlock):
    NAME = "latex"
    ARGUMENT = None

    def render(self, text):
        body = text.strip()
        cap = f'<figcaption>{html.escape(self.argument)}</figcaption>' if self.argument else ""
        return f'<figure class="aura-latex"><div class="arithmatex">\\[{html.escape(body)}\\]</div>{cap}</figure>'


class RawHtml(RawStashBlock):
    """HTML personalizzato: niente script, iframe o eventi; stili limitati ai colori/allineamenti."""
    NAME = "html"
    ARGUMENT = False

    def render(self, text):
        from ..render import sanitize

        return f'<div class="aura-html">{sanitize(text)}</div>'


def _host_ok(host: str) -> bool:
    host = host.lower()
    for allowed in settings.embed_allowed_hosts:
        if allowed.startswith("*.") and (host.endswith(allowed[1:]) or host == allowed[2:]):
            return True
        if host == allowed:
            return True
    return False


def embed_src(url: str) -> str:
    """Converte i link «normali» dei servizi più comuni nella loro versione incorporabile."""
    u = urlsplit(url)
    host = u.netloc.lower()
    if host.endswith("youtube.com") and u.path == "/watch":
        vid = parse_qs(u.query).get("v", [""])[0]
        return f"https://www.youtube-nocookie.com/embed/{quote(vid)}"
    if host == "youtu.be":
        return f"https://www.youtube-nocookie.com/embed/{quote(u.path.strip('/'))}"
    if host.endswith("figma.com") and "/embed" not in u.path:
        return f"https://www.figma.com/embed?embed_host=ailadoc&url={quote(url, safe='')}"
    if host == "miro.com" and u.path.startswith("/app/board/"):
        bid = u.path.split("/")[3]
        return f"https://miro.com/app/live-embed/{quote(bid)}/"
    if host == "vimeo.com":
        return f"https://player.vimeo.com/video/{quote(u.path.strip('/'))}"
    if host == "www.loom.com" and u.path.startswith("/share/"):
        return url.replace("/share/", "/embed/", 1)
    if host == "docs.google.com" and re.search(r"/(edit|view)/?$", u.path):
        path = re.sub(r"/(edit|view)/?$", "/preview", u.path)
        return f"https://{u.netloc}{path}" + (f"?{u.query}" if u.query else "")
    return url


class Embed(RawStashBlock):
    NAME = "embed"
    ARGUMENT = True
    ERROR_TITLE = "Contenuto non incorporabile"
    OPTIONS = {"height": ("", type_text), "ratio": ("", _choice("16:9", "4:3", "1:1", "21:9")),
               "title": ("", type_text)}

    def on_markdown(self):
        return "raw"

    def render(self, text):
        url = self.argument.strip()
        u = urlsplit(url)
        if u.scheme != "https" or not u.netloc:
            raise ValueError("Serve un indirizzo https://")
        if not _host_ok(u.hostname or ""):
            raise ValueError(f"Il sito {u.hostname} non è tra quelli ammessi (EMBED_ALLOWED_HOSTS).")
        src = embed_src(url)
        title = self.options["title"] or u.hostname
        h = self.options["height"]
        style, cls = "", "aura-embed"
        if h.isdigit():
            style = f' style="height:{min(int(h), 2000)}px"'
        else:
            cls += f" ratio-{(self.options['ratio'] or '16:9').replace(':', 'x')}"
        cap = f'<figcaption><a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{html.escape(title)} ↗</a></figcaption>'
        return (f'<figure class="{cls}"><div class="aura-embed-frame"{style}><iframe src="{html.escape(src)}" '
                f'title="{html.escape(title)}" loading="lazy" allowfullscreen referrerpolicy="strict-origin-when-cross-origin" '
                f'sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-presentation"></iframe></div>'
                f'{cap}</figure>')


_HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)


def md_section(body: str, anchor: str) -> str | None:
    """Testo della sezione con id ``anchor`` (fino al titolo successivo di pari livello o superiore)."""
    heads = list(_HEAD_RE.finditer(body))
    for i, m in enumerate(heads):
        title = re.sub(r"[*_`]", "", m.group(2))
        if slugify(title, "-") == anchor:
            level = len(m.group(1))
            end = len(body)
            for n in heads[i + 1:]:
                if len(n.group(1)) <= level:
                    end = n.start()
                    break
            return body[m.start():end]
    return None


class Include(RawStashBlock):
    """Cita (include) un'altra pagina o una sola sezione: ``/// include | ../altra.md#sezione``."""
    NAME = "include"
    ARGUMENT = True
    ERROR_TITLE = "Inclusione non riuscita"
    OPTIONS = {"source": (True, type_bool), "heading": (False, type_bool), "style": ("", _choice("plain", "quote", "card"))}

    def render(self, text):
        from ..render import render_markdown

        rel, frag = self.ctx.resolve(self.argument, kinds=("markdown",))
        p = storage.abs_path(rel)
        src = p.read_text(encoding="utf-8", errors="replace")
        meta, body = storage.split_front_matter(src)
        if frag:
            sec = md_section(body, frag)
            if sec is None:
                raise RefError(f"Sezione «{frag}» non trovata in {rel}.")
            body = sec
        elif not self.options["heading"]:
            body = re.sub(r"\A\s*#\s+.+\n", "", body, count=1)
        child = self.ctx.child(rel)
        inner, _, _ = render_markdown(body, rel, child.can_view, ctx=child)
        title = storage.md_title(p) or storage.pretty(p.name)
        head = ""
        if self.options["source"]:
            head = (f'<div class="aura-include-src"><span>Da</span> <a href="{html.escape(doc_url(rel, "#" + frag if frag else ""))}">'
                    f'{html.escape(title)}</a></div>')
        style = self.options["style"] or "quote"
        return f'<div class="aura-include aura-include-{style}">{head}<div class="aura-include-body">{inner}</div></div>'


KIND_EMOJI = {"folder": "📁", "markdown": "📄", "pdf": "📕", "slides": "📙", "sheet": "📗", "word": "📘",
              "image": "🖼️", "video": "🎬", "audio": "🎵", "archive": "🗜️", "text": "📃", "diagram": "🧭"}


class Pages(CtxBlock):
    """Panoramica dinamica: elenca le pagine e i file di una cartella visibili a chi legge."""
    NAME = "pages"
    ARGUMENT = None
    OPTIONS = {"style": ("", _choice("cards", "list", "compact")), "limit": ("", type_text),
               "files": (True, type_bool), "folders": (True, type_bool), "description": (True, type_bool)}

    def on_create(self, parent):
        ctx = self.ctx
        ref = (self.argument or "").strip()
        style = self.options["style"] or "cards"
        try:
            if ref in ("", "."):
                folder = ctx.doc_dir
            else:
                base = "" if ref.startswith("/") else ctx.doc_dir
                target = posixpath.normpath(posixpath.join(base, ref.lstrip("/")))
                if target.startswith(".."):
                    raise RefError(f"La cartella «{ref}» non esiste.")
                folder = storage.clean_rel("" if target == "." else target)
            p = storage.abs_path(folder)
            if not p.is_dir():
                raise RefError(f"La cartella «{ref}» non esiste.")
            node = storage.build_tree(folder)
        except (RefError, storage.PathError) as e:
            el = etree.SubElement(parent, "div", {"class": "plug-error"})
            el.text = str(e) if isinstance(e, RefError) else "Cartella non valida."
            return el
        items = []
        for c in node.children:
            if c.is_dir:
                if not self.options["folders"]:
                    continue
                if not ctx.can_view(c.path) or (c.index and not ctx.can_view(c.index)):
                    continue
                items.append((c, f"/d/{quote(c.path)}", "folder"))
            else:
                if c.path == ctx.doc_path or not ctx.can_view(c.path):
                    continue
                if c.kind != "markdown" and not self.options["files"]:
                    continue
                items.append((c, f"/d/{quote(c.path)}", c.kind))
        lim = self.options["limit"]
        if lim.isdigit():
            items = items[: int(lim)]
        el = etree.SubElement(parent, "div", {"class": f"aura-pages aura-pages-{style}"})
        if not items:
            etree.SubElement(el, "p", {"class": "muted"}).text = "Nessun contenuto da mostrare."
            return el
        for node_, href, kind in items:
            item = etree.SubElement(el, "div", {"class": f"aura-page kind-{kind}"})
            etree.SubElement(item, "span", {"class": "aura-page-icon", "aria-hidden": "true"}).text = KIND_EMOJI.get(kind, "📄")
            box = etree.SubElement(item, "div", {"class": "aura-page-text"})
            etree.SubElement(box, "a", {"class": "aura-page-title aura-stretched", "href": href}).text = node_.title
            if style != "compact" and self.options["description"]:
                desc = _description(node_, ctx)
                if desc:
                    etree.SubElement(box, "div", {"class": "aura-page-desc"}).text = desc
        return el

    def on_add(self, block):
        return etree.Element("div")


def _description(node: storage.Node, ctx: RenderCtx) -> str:
    path = node.index if node.is_dir else (node.path if node.kind == "markdown" else None)
    if node.is_dir and not path:
        n = sum(1 for c in node.children if ctx.can_view(c.path))
        return f"{n} elementi" if n != 1 else "1 elemento"
    if not path:
        return storage.KIND_LABELS.get(node.kind, "File")
    try:
        text = storage.abs_path(path).read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return ""
    meta, body = storage.split_front_matter(text)
    if meta.get("description"):
        return str(meta["description"])[:180]
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para or para.startswith(("#", "!!!", "///", "```", "|", "<", "-", "*", ">", "===")):
            continue
        para = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", para)
        para = re.sub(r"[*_`]", "", para).replace("\n", " ")
        return para[:177] + ("…" if len(para) > 177 else "")
    return ""


# ------------------------------------------------------------------- inline: {{status: ...}}
_INLINE = r"\{\{\s*(status|badge|icon)\s*:\s*([^}|]+?)\s*(?:\|\s*([^}|]*?)\s*)?(?:\|\s*([^}|]*?)\s*)?\}\}"


class _InlineMacro(InlineProcessor):
    def handleMatch(self, m, data):
        kind, text, color, style = m.group(1), m.group(2), m.group(3) or "", (m.group(4) or "").lower()
        if kind == "icon":
            el = etree.Element("span", {"class": "aura-icon-inline", "aria-hidden": "true"})
            el.text = icon_text(text)
            return el, m.start(0), m.end(0)
        attrs = merge_class(color_attrs(color, "gray"), "aura-status",
                            f"aura-{style}" if style in ("solid", "outline", "soft") else "aura-soft")
        el = etree.Element("span", attrs)
        el.text = text
        return el, m.start(0), m.end(0)


class _InlineExt(Extension):
    def extendMarkdown(self, md):
        md.inlinePatterns.register(_InlineMacro(_INLINE, md), "ailadoc_inline_macros", 175)


BLOCKS = (Panel, Expand, Tabs, Columns, Column, Background, Divider, Title, Hero, Cards, Card, Button,
          Progress, Countdown, Latex, RawHtml, Embed, Include, Pages)


def _extensions(ctx: RenderCtx) -> list:
    from pymdownx.arithmatex import ArithmatexExtension
    from pymdownx.blocks.tab import TabExtension

    return [blocks_extension(*BLOCKS), TabExtension(alternate_style=True), _InlineExt(),
            ArithmatexExtension(generic=True)]


EX_PANEL = """/// panel | Prima di iniziare
    color: blue
    icon: info

Verifica di avere accesso alla **VPN** aziendale.
///

/// panel | Attenzione
    color: orange
    icon: warning
    style: left

I dati di produzione si modificano solo dopo l'approvazione.
///"""

EX_CARDS = """//// cards
    columns: 3

/// card | Guida rapida
    icon: rocket
    link: index.md

I primi passi per orientarsi.
///

/// card | Procedure
    icon: clipboard
    color: green
    badge: Aggiornato

Come si gestiscono resi e non conformità.
///

/// card | Supporto
    icon: support
    color: purple
    link: https://example.com

Apri una richiesta all'IT.
///
////"""

EX_HERO = """/// hero | Portale documentale
    subtitle: Tutto quello che serve per lavorare, in un unico posto
    color: teal
    icon: book

/// button | Inizia da qui
    link: index.md
    color: yellow
///
///"""

EX_TABS = """//// tabs
    style: vertical

/// tab | Windows
Apri **Impostazioni → Rete**.
///

/// tab | macOS
Apri **Impostazioni di Sistema → Rete**.
///

/// tab | Linux
Usa `nmcli`.
///
////"""

EX_COLUMNS = """//// columns

/// column | 2/3
### Descrizione
Testo principale su due terzi della pagina.
///

/// column | 1/3
    color: yellow

**Contatti**
{{icon: mail}} it@example.com
///
////"""

EX_DATA = """Stato del progetto: {{status: In corso | blue}} · Revisione {{status: Approvata | green | solid}} · {{status: Bloccante | red | outline}}

/// progress | 7/10
    label: Migrazione dei server
///

/// countdown | 2026-12-31 18:00
    label: Chiusura dell'anno fiscale
    done: Chiuso!
///"""

EX_TITLE = """/// title | Sezione con stile
    subtitle: Un titolo con sottotitolo, colore e icona
    icon: target
    color: purple
    style: bar
///

/// divider | Parte seconda
    style: dashed
    icon: star
///

/// background
    color: yellow

Un'area con **sfondo colorato** per mettere in evidenza un blocco di testo.
///"""

EX_ADV = """Formula in linea $E = mc^2$ e in un blocco:

/// latex | Media ponderata
\\bar{x} = \\frac{\\sum_{i=1}^{n} w_i x_i}{\\sum_{i=1}^{n} w_i}
///

/// expand | Dettagli tecnici
    icon: gear

Contenuto nascosto finché non si apre.
///

/// html
<p style="text-align:center; color:#0d6e5c"><strong>HTML personalizzato</strong> (senza script)</p>
///"""

EX_EMBED = """/// embed | https://www.youtube.com/watch?v=dQw4w9WgXcQ
    title: Video di presentazione
///

/// include | altra-pagina.md#una-sezione
///

/// pages | .
    style: cards
///"""

PLUGIN = Plugin(
    id="macros", name="Macro di formattazione", icon="sparkle",
    description=("Pannelli, card, pulsanti, hero, titoli, divisori, sfondi, colonne, tab verticali, "
                 "sezioni espandibili, stato, barre di avanzamento, countdown, formule LaTeX, HTML, "
                 "contenuti incorporati (Figma, Miro, Google, Microsoft 365, YouTube…), inclusione "
                 "di altre pagine e panoramiche dinamiche delle cartelle."),
    extensions=_extensions,
    snippets=[
        {"label": "Pannello", "icon": "ℹ️", "text": "/// panel | Titolo\n    color: blue\n    icon: info\n\nTesto del pannello.\n///"},
        {"label": "Card", "icon": "🗂️", "text": EX_CARDS},
        {"label": "Pulsante", "icon": "🔘", "text": "/// button | Apri\n    link: pagina.md\n    color: accent\n///"},
        {"label": "Hero", "icon": "🏞️", "text": "/// hero | Titolo grande\n    subtitle: Sottotitolo\n    color: teal\n\nTesto introduttivo.\n///"},
        {"label": "Titolo con stile", "icon": "🔠", "text": "/// title | Titolo\n    subtitle: Sottotitolo\n    style: bar\n    color: accent\n///"},
        {"label": "Divisore", "icon": "➖", "text": "/// divider | Testo\n    style: dashed\n///"},
        {"label": "Sfondo", "icon": "🎨", "text": "/// background\n    color: yellow\n\nTesto evidenziato.\n///"},
        {"label": "Colonne", "icon": "▥", "text": EX_COLUMNS},
        {"label": "Tab", "icon": "🗃️", "text": "//// tabs\n\n/// tab | Primo\nContenuto.\n///\n\n/// tab | Secondo\nContenuto.\n///\n////"},
        {"label": "Sezione espandibile", "icon": "🔽", "text": "/// expand | Mostra dettagli\n\nContenuto nascosto.\n///"},
        {"label": "Stato", "icon": "🏷️", "text": "{{status: In corso | blue}}", "inline": True},
        {"label": "Barra di avanzamento", "icon": "📶", "text": "/// progress | 60\n    label: Avanzamento\n///"},
        {"label": "Countdown", "icon": "⏳", "text": "/// countdown | 2026-12-31 18:00\n    label: Scadenza\n///"},
        {"label": "Formula LaTeX", "icon": "∑", "text": "/// latex\nx = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}\n///"},
        {"label": "HTML personalizzato", "icon": "</>", "text": "/// html\n<p style=\"text-align:center\">HTML</p>\n///"},
        {"label": "Incorpora (Figma, Miro, Google…)", "icon": "🪟", "text": "/// embed | https://\n    height: 480\n///"},
        {"label": "Includi un'altra pagina", "icon": "📎", "action": "include"},
        {"label": "Elenco pagine della cartella", "icon": "🗂️", "text": "/// pages | .\n    style: cards\n///"},
    ],
    examples=[
        ("Pannelli", EX_PANEL), ("Card", EX_CARDS), ("Hero e pulsanti", EX_HERO), ("Tab verticali", EX_TABS),
        ("Colonne", EX_COLUMNS), ("Stato, avanzamento e countdown", EX_DATA),
        ("Titoli, divisori e sfondi", EX_TITLE), ("LaTeX, espandibili e HTML", EX_ADV),
        ("Incorporare e citare", EX_EMBED, False),
    ],
)
