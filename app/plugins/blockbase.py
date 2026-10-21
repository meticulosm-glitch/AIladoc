"""Basi comuni per i blocchi ``/// nome`` dei plugin (pymdownx.blocks)."""
from __future__ import annotations

import xml.etree.ElementTree as etree
from typing import Any

from markdown.treeprocessors import Treeprocessor
from pymdownx.blocks import BlocksExtension
from pymdownx.blocks.block import Block

from . import RefError, RenderCtx, error_box


def type_text(v: Any) -> str:
    """Qualsiasi valore scalare YAML come stringa (YAML trasforma 2026-12-31 in data, 60 in int...)."""
    if isinstance(v, (dict, list)):
        raise ValueError("atteso un valore semplice")
    return "" if v is None else str(v).strip()


def type_any(v: Any) -> Any:
    return v


def type_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "si", "sì", "on", "vero")


class CtxBlock(Block):
    """Blocco con accesso al contesto di rendering (documento, permessi, stash)."""

    @property
    def ctx(self) -> RenderCtx:
        return self.md.ailadoc_ctx  # impostato da render_markdown


class RawStashBlock(CtxBlock):
    """Blocco il cui contenuto è testo grezzo trasformato in HTML sicuro dal plugin.

    Sottoclassi: implementare ``render(text) -> str`` (HTML già sicuro) e, se serve,
    sollevare RefError/ValueError per mostrare un riquadro d'errore leggibile.
    """

    ARGUMENT = None
    ERROR_TITLE = "Macro non valida"

    def on_markdown(self) -> str:
        return "raw"

    def on_create(self, parent: etree.Element) -> etree.Element:
        return etree.SubElement(parent, "div", {"class": "ailaplug-slot"})

    def on_end(self, block: etree.Element) -> None:
        text = block.text or ""
        try:
            out = self.render(str(text))
        except (RefError, ValueError) as e:
            out = error_box(str(e), self.ERROR_TITLE)
        for child in list(block):
            block.remove(child)
        block.text = self.ctx.put(out)

    def render(self, text: str) -> str:  # pragma: no cover - astratto
        raise NotImplementedError


class _Unparsed(Treeprocessor):
    """Un blocco ``/// nome`` rimasto testo (opzione sbagliata, YAML non valido): lo segnala."""

    def run(self, root):
        for p in root.iter("p"):
            if (p.text or "").lstrip().startswith("///") and p.get("class") is None:
                p.set("class", "plug-unparsed")


def blocks_extension(*blocks: type[Block]) -> BlocksExtension:
    class _Ext(BlocksExtension):
        def extendMarkdownBlocks(self, md, block_mgr):
            for b in blocks:
                block_mgr.register(b, {})
            if "ailadoc_unparsed" not in md.treeprocessors:
                md.treeprocessors.register(_Unparsed(md), "ailadoc_unparsed", 3)

    return _Ext()
