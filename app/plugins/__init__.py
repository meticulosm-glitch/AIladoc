"""Plugin di AIladoc: macro Markdown che citano e incorporano contenuti di altri servizi.

Ogni plugin aggiunge estensioni Markdown (blocchi ``/// nome``), CSS/JS lato browser,
voci del menu «Inserisci» dell'editor ed esempi per la pagina di guida (/plugins).

- ``drawio``  diagrammi draw.io: visualizzazione, incorporamento nelle pagine, modifica nel browser
- ``tables``  tabelle dinamiche da Excel/CSV o scritte nella pagina: filtri, ordinamento,
              colonne calcolate, raggruppamenti, pivot, totali e grafici
- ``macros``  macro di formattazione: pannelli, card, pulsanti, hero, tab, colonne, stato,
              barre di avanzamento, countdown, LaTeX, HTML, embed, inclusione di pagine...

Si attivano con la variabile ``PLUGINS`` (default: tutti).

Sicurezza: tutto l'HTML prodotto dal Markdown passa da nh3. I plugin che devono produrre
markup non ammesso dal sanitizer (iframe, SVG, tabelle con attributi data-*) lo generano
loro stessi con escaping esplicito e lo "parcheggiano" in ``RenderCtx.stash``: dopo la
sanitizzazione il segnaposto (con un nonce casuale per richiesta, non indovinabile da chi
scrive la pagina) viene sostituito dall'HTML del plugin. I riferimenti ad altri documenti
passano sempre da ``RenderCtx.resolve``, che applica i permessi dell'utente che legge.
"""
from __future__ import annotations

import html
import posixpath
import re
import secrets
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote, unquote, urlsplit

from .. import storage
from ..config import settings

MAX_DEPTH = 3  # inclusioni annidate (pagina che include una pagina che ne include un'altra...)


class RefError(Exception):
    """Riferimento a un documento non valido, inesistente o non visibile all'utente."""


@dataclass
class RenderCtx:
    doc_path: str
    can_view: Callable[[str], bool] = field(default=lambda _rel: False)
    depth: int = 0
    stack: tuple[str, ...] = ()
    nonce: str = field(default_factory=lambda: secrets.token_hex(8))
    stash: dict[str, str] = field(default_factory=dict)

    @property
    def doc_dir(self) -> str:
        return posixpath.dirname(self.doc_path)

    # ---------------------------------------------------------------- stash
    def put(self, trusted_html: str, block: bool = True) -> str:
        """Parcheggia HTML già sicuro; ritorna il segnaposto da mettere nel Markdown/etree."""
        key = f"AILAPLUG{self.nonce}N{len(self.stash)}Z"
        self.stash[key] = trusted_html
        return key

    def unstash(self, cleaned: str) -> str:
        if not self.stash:
            return cleaned
        pat = re.compile(r'(?:<(p|div)(?: class="ailaplug-slot")?>\s*)?(AILAPLUG' + self.nonce + r'N\d+Z)(?:\s*</\1>)?')

        def repl(m: re.Match) -> str:
            return self.stash.get(m.group(2), "")

        return pat.sub(repl, cleaned)

    # ----------------------------------------------------------- riferimenti
    def resolve(self, ref: str, kinds: tuple[str, ...] | None = None) -> tuple[str, str]:
        """Risolve un riferimento (relativo alla pagina, o assoluto se inizia con '/').

        Ritorna (percorso, frammento). Solleva RefError se il file non esiste, è fuori dalla
        radice, è del tipo sbagliato o l'utente non può vederlo (stesso messaggio: non si
        rivela l'esistenza di documenti riservati).
        """
        ref = (ref or "").strip()
        if not ref:
            raise RefError("Manca il percorso del file.")
        parts = urlsplit(ref)
        if parts.scheme or parts.netloc:
            raise RefError("Indica un file della documentazione, non un indirizzo web.")
        path = unquote(parts.path)
        base = "" if path.startswith("/") else self.doc_dir
        target = posixpath.normpath(posixpath.join(base, path.lstrip("/")))
        if target in (".", "") or target.startswith(".."):
            raise RefError(f"Percorso non valido: {ref}")
        try:
            rel = storage.clean_rel(target)
            p = storage.abs_path(rel)
        except storage.PathError as e:
            raise RefError(f"Percorso non valido: {ref}") from e
        if not p.is_file() or not self.can_view(rel):
            raise RefError(f"«{ref}» non esiste o non hai i permessi per vederlo.")
        if kinds and storage.kind_of(p.name) not in kinds:
            raise RefError(f"«{ref}» non è del tipo atteso.")
        return rel, parts.fragment

    def child(self, doc_path: str) -> "RenderCtx":
        if self.depth + 1 > MAX_DEPTH or doc_path in self.stack or doc_path == self.doc_path:
            raise RefError("Inclusione circolare o troppo annidata.")
        return RenderCtx(doc_path, self.can_view, self.depth + 1, self.stack + (self.doc_path,))


def error_box(msg: str, title: str = "Macro non valida") -> str:
    return (f'<div class="plug-error" role="note"><strong>{html.escape(title)}</strong> '
            f'<span>{html.escape(msg)}</span></div>')


def doc_url(rel: str, anchor: str = "") -> str:
    return f"/d/{quote(rel)}{anchor}"


def raw_url(rel: str) -> str:
    return f"/raw/{quote(rel)}"


# ----------------------------------------------------------------- colori
COLORS = {
    "blue": "blue", "blu": "blue", "azzurro": "blue", "info": "blue",
    "green": "green", "verde": "green", "success": "green", "ok": "green",
    "red": "red", "rosso": "red", "danger": "red", "error": "red",
    "yellow": "yellow", "giallo": "yellow", "warning": "yellow", "warn": "yellow",
    "orange": "orange", "arancione": "orange", "arancio": "orange",
    "purple": "purple", "viola": "purple",
    "teal": "teal", "turchese": "teal", "petrolio": "teal",
    "pink": "pink", "rosa": "pink",
    "gray": "gray", "grey": "gray", "grigio": "gray", "neutral": "gray", "neutro": "gray",
    "accent": "accent", "primary": "accent", "primario": "accent", "brand": "accent",
}
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def color_attrs(value: str | None, default: str = "") -> dict[str, str]:
    """Colore preimpostato (classe c-<nome>) o esadecimale (variabile CSS --c)."""
    v = (value or default or "").strip().lower()
    if not v:
        return {}
    if v in COLORS:
        return {"class": f"c-{COLORS[v]}"}
    if _HEX.match(v):
        return {"class": "c-custom", "style": f"--c: {v}"}
    return {"class": f"c-{COLORS.get(default, 'accent')}"} if default else {}


def merge_class(attrs: dict[str, str], *classes: str) -> dict[str, str]:
    out = dict(attrs)
    out["class"] = " ".join(c for c in (*classes, attrs.get("class", "")) if c)
    return out


# ----------------------------------------------------------------- registro
@dataclass
class Plugin:
    id: str
    name: str
    description: str
    icon: str
    extensions: Callable[[RenderCtx], list]
    snippets: list[dict] = field(default_factory=list)
    examples: list[tuple[str, str]] = field(default_factory=list)


def _registry() -> dict[str, Plugin]:
    from . import drawio, macros, tables

    return {p.id: p for p in (drawio.PLUGIN, tables.PLUGIN, macros.PLUGIN)}


ALL: dict[str, Plugin] = {}


def enabled() -> list[Plugin]:
    global ALL
    if not ALL:
        ALL = _registry()
    wanted = settings.plugins
    if wanted == ["all"]:
        return list(ALL.values())
    return [ALL[w] for w in wanted if w in ALL]


def is_enabled(pid: str) -> bool:
    return any(p.id == pid for p in enabled())


def extensions(ctx: RenderCtx) -> list:
    out: list = []
    for p in enabled():
        out += p.extensions(ctx)
    return out


def snippets() -> list[dict]:
    out = []
    for p in enabled():
        for s in p.snippets:
            out.append({"plugin": p.id, "group": p.name, **s})
    return out
