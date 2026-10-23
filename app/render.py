"""Rendering Markdown (stesse estensioni tipiche di MkDocs Material) con sanitizzazione."""
from __future__ import annotations

import html
import posixpath
from typing import Callable
from urllib.parse import quote, unquote, urlsplit

import markdown
import nh3
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor
from pygments.formatters import HtmlFormatter

from . import plugins
from .storage import split_front_matter


def _mermaid_fence(source, language, css_class, options, md, **kwargs):
    return f'<pre class="mermaid">{html.escape(source)}</pre>'


EXTENSIONS = [
    "abbr", "attr_list", "def_list", "footnotes", "md_in_html", "tables", "admonition",
    "toc", "sane_lists",
    "pymdownx.highlight", "pymdownx.inlinehilite", "pymdownx.superfences",
    "pymdownx.details", "pymdownx.tabbed", "pymdownx.tasklist", "pymdownx.mark",
    "pymdownx.tilde", "pymdownx.caret", "pymdownx.keys", "pymdownx.smartsymbols",
    "pymdownx.magiclink",
]
EXT_CONFIG = {
    "toc": {"permalink": "#", "permalink_title": "Link a questa sezione", "toc_depth": "2-4"},
    "pymdownx.highlight": {"anchor_linenums": False, "use_pygments": True, "css_class": "highlight"},
    "pymdownx.superfences": {"custom_fences": [{"name": "mermaid", "class": "mermaid", "format": _mermaid_fence}]},
    "pymdownx.tabbed": {"alternate_style": True},
    "pymdownx.tasklist": {"custom_checkbox": True},
}

ALLOWED_TAGS = set(nh3.ALLOWED_TAGS) | {
    "details", "summary", "input", "label", "span", "div", "pre", "code", "sup", "sub", "mark",
    "del", "ins", "kbd", "abbr", "dl", "dt", "dd", "figure", "figcaption", "table", "thead",
    "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col", "hr", "br", "img",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "aside", "video", "audio", "source",
}
ALLOWED_ATTRS = {
    "*": {"class", "id", "title", "align"},
    "a": {"href", "name", "target"},
    "img": {"src", "alt", "width", "height", "loading"},
    "input": {"type", "checked", "disabled", "name"},
    "label": {"for"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "details": {"open"},
    "ol": {"start", "type"},
    "video": {"src", "controls", "width", "height", "poster"},
    "audio": {"src", "controls"},
    "source": {"src", "type"},
    "abbr": set(),
    "span": {"data-countdown", "data-done"},
    "div": {"data-countdown", "data-done"},
}
# "style" serve ai colori personalizzati delle macro (--c: #hex): solo queste proprietà sopravvivono
ALLOWED_ATTRS["*"] = ALLOWED_ATTRS["*"] | {"style"}
ALLOWED_STYLE = {
    "--c", "color", "background-color", "border-color", "text-align", "font-weight", "font-style",
    "text-decoration", "width", "max-width",
}


def _is_relative(url: str) -> bool:
    if not url or url.startswith(("#", "/", "//")):
        return False
    if "\x02" in url or "\x03" in url:  # segnaposto di Markdown (es. mailto offuscato da magiclink)
        return False
    parts = urlsplit(url)
    return not parts.scheme and not parts.netloc


def resolve_link(doc_dir: str, url: str) -> tuple[str, str] | None:
    """Ritorna (percorso_relativo_risolto, frammento) o None se esce dalla radice."""
    parts = urlsplit(url)
    # il percorso nel Markdown è URL-encoded (foto%20uno.png): va decodificato, altrimenti
    # il quote() successivo lo codifica due volte (foto%2520uno.png) e il file non si trova
    target = posixpath.normpath(posixpath.join(doc_dir, unquote(parts.path))) if parts.path else ""
    if target == ".":
        target = ""
    if target.startswith(".."):
        return None
    return target, (f"#{parts.fragment}" if parts.fragment else "")


class _LinkRewriter(Treeprocessor):
    def __init__(self, md, doc_dir: str):
        super().__init__(md)
        self.doc_dir = doc_dir

    def run(self, root):
        for el in root.iter():
            for attr, prefix in (("href", "/d/"), ("src", "/raw/")):
                if el.tag not in ("a", "img", "source", "video", "audio") or attr not in el.attrib:
                    continue
                url = el.get(attr)
                if not _is_relative(url):
                    continue
                res = resolve_link(self.doc_dir, url)
                if res is None:
                    continue
                target, frag = res
                if not urlsplit(url).path:  # solo "#ancora"
                    continue
                pre = prefix if el.tag == "a" else "/raw/"
                el.set(attr, pre + quote(target) + frag)


class _LinkExt(Extension):
    def __init__(self, doc_dir: str):
        super().__init__()
        self.doc_dir = doc_dir

    def extendMarkdown(self, md):
        md.treeprocessors.register(_LinkRewriter(md, self.doc_dir), "ailadoc_links", 5)


def render_markdown(text: str, doc_path: str, can_view: Callable[[str], bool] | None = None, *,
                    use_plugins: bool = True, ctx: "plugins.RenderCtx | None" = None) -> tuple[str, list, dict]:
    """Ritorna (html_sicuro, toc_tokens, front_matter).

    ``can_view`` decide quali documenti le macro possono citare/incorporare (di default nessuno):
    va passato il controllo permessi dell'utente che sta leggendo.
    """
    meta, body = split_front_matter(text)
    doc_dir = posixpath.dirname(doc_path)
    ctx = ctx or plugins.RenderCtx(doc_path, can_view or (lambda _rel: False))
    exts = EXTENSIONS + [_LinkExt(doc_dir)] + (plugins.extensions(ctx) if use_plugins else [])
    md = markdown.Markdown(extensions=exts, extension_configs=EXT_CONFIG)
    md.ailadoc_ctx = ctx
    raw = md.convert(body)
    safe = sanitize(raw)
    return ctx.unstash(safe), getattr(md, "toc_tokens", []), meta


def sanitize(raw: str) -> str:
    return nh3.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, link_rel="noopener noreferrer",
                     strip_comments=True, filter_style_properties=ALLOWED_STYLE)


def pygments_css() -> str:
    light = HtmlFormatter(style="friendly").get_style_defs(".highlight")
    dark = HtmlFormatter(style="github-dark").get_style_defs(":root[data-theme=dark] .highlight")
    dark_auto = HtmlFormatter(style="github-dark").get_style_defs(":root:not([data-theme=light]) .highlight")
    return (
        light + "\n:root[data-theme=dark] .highlight{background:transparent}\n" + dark
        + "\n@media (prefers-color-scheme: dark){\n" + dark_auto
        + "\n:root:not([data-theme=light]) .highlight{background:transparent}}\n"
        + ".highlight{background:transparent}\n"
    )
