"""Creazione rapida di pagine e cartelle: singole, con percorso annidato o in blocco.

- "Procedure/Qualità/Controllo accessi"  -> crea le cartelle mancanti e la pagina
- "Procedure/Qualità/"                     -> solo cartelle (la "/" finale indica una cartella)
- struttura su più righe, il rientro indica l'annidamento:

      Procedure/
        Qualità/
          Controllo accessi
        Gestione resi
      Glossario

Le pagine ricevono un nome file "slug" (controllo-accessi.md) e il titolo come "# Titolo".
Un prefisso numerico (es. "01 Introduzione") resta nel nome del file per l'ordine del
menu ma non nel titolo. Le cartelle mantengono il nome scritto.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from . import storage
from .permissions import Perms

MAX_ITEMS = 200
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_ORDER = re.compile(r"^\d+[\s._-]+")


class CreateError(ValueError):
    pass


@dataclass
class Item:
    kind: str          # "page" | "folder"
    path: str
    title: str
    created: bool
    note: str = ""


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:80].strip("-")


def folder_name(text: str) -> str:
    name = re.sub(r"\s+", " ", _BAD_CHARS.sub("", text)).strip().strip(".").strip()
    if not name:
        raise CreateError(f"Nome di cartella non valido: «{text.strip()}»")
    return name[:120]


def page_title(text: str) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if t.lower().endswith(".markdown"):
        t = t[:-9].strip()
    elif t.lower().endswith(".md"):
        t = t[:-3].strip()
    return t


def page_filename(title: str) -> str:
    return (slugify(title) or "pagina") + ".md"


class Creator:
    def __init__(self, perms: Perms):
        self.perms = perms
        self.items: list[Item] = []

    # -- helpers ---------------------------------------------------------
    def _check_edit(self, rel: str) -> None:
        if not self.perms.can_edit(rel):
            raise CreateError(f"Non hai i permessi per creare contenuti in «/{rel}».")

    def _count(self) -> None:
        if len(self.items) > MAX_ITEMS:
            raise CreateError(f"Troppi elementi in una volta sola (massimo {MAX_ITEMS}).")

    # -- operazioni elementari ---------------------------------------------
    def ensure_folder(self, parent: str, raw: str, index: bool = False) -> str:
        self._check_edit(parent)
        name = folder_name(raw)
        rel = f"{parent}/{name}" if parent else name
        p = storage.abs_path(rel)
        if p.exists() and not p.is_dir():
            raise CreateError(f"«{name}» esiste già come file in «/{parent}».")
        if p.is_dir():
            self.items.append(Item("folder", rel, name, False, "esiste già"))
        else:
            p.mkdir()
            self.items.append(Item("folder", rel, name, True))
        self._count()
        if index and not any((p / n).exists() for n in storage.INDEX_NAMES):
            title = _ORDER.sub("", name) or name
            (p / "index.md").write_text(f"# {title}\n\n", encoding="utf-8")
            self.items.append(Item("page", f"{rel}/index.md", title, True, "pagina della cartella"))
        return rel

    def create_page(self, parent: str, raw: str) -> str:
        self._check_edit(parent)
        title = page_title(raw)
        if not title:
            raise CreateError("Il titolo della pagina è vuoto.")
        rel = f"{parent}/{page_filename(title)}" if parent else page_filename(title)
        p = storage.abs_path(rel)
        if p.exists():
            self.items.append(Item("page", rel, title, False, "esiste già"))
        else:
            heading = _ORDER.sub("", title) or title
            p.write_text(f"# {heading}\n\n", encoding="utf-8")
            self.items.append(Item("page", rel, heading, True))
        self._count()
        return rel

    # -- operazioni composte ------------------------------------------------
    def create_path(self, parent: str, text: str, kind: str, index: bool = False) -> str:
        """Crea "a/b/c": cartelle intermedie + pagina (o cartella) finale."""
        parent = storage.clean_rel(parent)
        text = text.strip()
        if text.endswith("/"):
            kind = "folder"
        segs = [s.strip() for s in text.strip("/").split("/") if s.strip()]
        if not segs:
            raise CreateError("Scrivi un titolo.")
        if any(s in (".", "..") for s in segs):
            raise CreateError("Percorso non valido.")
        cur = parent
        for s in segs[:-1]:
            cur = self.ensure_folder(cur, s)
        if kind == "folder":
            return self.ensure_folder(cur, segs[-1], index=index)
        return self.create_page(cur, segs[-1])

    def create_tree(self, parent: str, text: str, index: bool = False) -> None:
        parent = storage.clean_rel(parent)
        lines: list[tuple[int, str]] = []
        for raw in text.replace("\r\n", "\n").split("\n"):
            expanded = raw.replace("\t", "    ")
            content = expanded.strip()
            if not content or content.startswith("#"):
                continue
            indent = len(expanded) - len(expanded.lstrip(" "))
            lines.append((indent, _BULLET.sub("", content).strip()))
        if not lines:
            raise CreateError("Scrivi almeno una riga.")
        if len(lines) > MAX_ITEMS:
            raise CreateError(f"Troppe righe (massimo {MAX_ITEMS}).")
        stack: list[tuple[int, str]] = []
        for i, (indent, content) in enumerate(lines):
            while stack and stack[-1][0] >= indent:
                stack.pop()
            base = stack[-1][1] if stack else parent
            next_indent = lines[i + 1][0] if i + 1 < len(lines) else -1
            is_folder = content.endswith("/") or next_indent > indent
            rel = self.create_path(base, content, "folder" if is_folder else "page", index=index and is_folder)
            if is_folder:
                stack.append((indent, rel))

    def as_dicts(self) -> list[dict]:
        return [asdict(i) for i in self.items]
