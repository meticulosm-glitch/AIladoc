"""Accesso al filesystem dei documenti: percorsi sicuri, tipi di file, albero."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from .config import settings

KINDS: dict[str, tuple[str, ...]] = {
    "markdown": ("md", "markdown"),
    "pdf": ("pdf",),
    "slides": ("ppt", "pptx", "pps", "ppsx", "odp", "key"),
    "sheet": ("xls", "xlsx", "xlsm", "ods", "csv", "tsv", "numbers"),
    "word": ("doc", "docx", "odt", "rtf", "pages"),
    "image": ("png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"),
    "video": ("mp4", "webm", "mov", "m4v"),
    "audio": ("mp3", "wav", "ogg", "m4a"),
    "archive": ("zip", "7z", "tar", "gz", "tgz", "rar"),
    "text": ("txt", "json", "yaml", "yml", "xml", "log", "ini", "toml", "sql"),
    "diagram": ("drawio", "dio"),
}
EXT_TO_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}
KIND_LABELS = {
    "markdown": "Pagina", "pdf": "PDF", "slides": "Presentazione", "sheet": "Foglio di calcolo",
    "word": "Documento", "image": "Immagine", "video": "Video", "audio": "Audio",
    "archive": "Archivio", "text": "Testo", "diagram": "Diagramma", "file": "File", "folder": "Cartella",
}
ALLOWED_UPLOAD_EXT = set(EXT_TO_KIND)
INDEX_NAMES = ("index.md", "README.md", "readme.md")
_ORDER_PREFIX = re.compile(r"^\d+[\s._-]+")
_SEGMENT_OK = re.compile(r"^[^/\\\x00]+$")


class PathError(ValueError):
    pass


def kind_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return EXT_TO_KIND.get(ext, "file")


def clean_rel(rel: str) -> str:
    """Normalizza e valida un percorso relativo alla radice dei documenti."""
    rel = (rel or "").strip().strip("/")
    if not rel:
        return ""
    parts = []
    for seg in rel.split("/"):
        if seg in ("", "."):
            continue
        if seg == ".." or seg.startswith(".") or not _SEGMENT_OK.match(seg):
            raise PathError(f"Percorso non valido: {rel!r}")
        parts.append(seg)
    return "/".join(parts)


def abs_path(rel: str) -> Path:
    rel = clean_rel(rel)
    root = settings.docs_dir.resolve()
    p = (root / rel).resolve() if rel else root
    if p != root and root not in p.parents:
        raise PathError("Percorso fuori dalla radice")
    return p


def parent_of(rel: str) -> str:
    parent = str(PurePosixPath(rel).parent)
    return "" if parent == "." else parent


def ancestors(rel: str) -> list[str]:
    """Percorso stesso e tutti gli antenati, dal più profondo alla radice ('')."""
    rel = clean_rel(rel)
    out = []
    while True:
        out.append(rel)
        if not rel:
            break
        rel = parent_of(rel)
    return out


def pretty(name: str) -> str:
    stem = name
    if "." in name and not name.startswith("."):
        stem = name.rsplit(".", 1)[0]
    stem = _ORDER_PREFIX.sub("", stem)
    return stem.replace("_", " ").strip() or name


# --- Front matter e titoli -------------------------------------------------
_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
_H1 = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)
_title_cache: dict[str, tuple[float, str | None]] = {}


def split_front_matter(text: str) -> tuple[dict, str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta, dict):
            meta = {}
    except yaml.YAMLError:
        meta = {}
    return meta, text[m.end():]


def md_title(p: Path) -> str | None:
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    key = str(p)
    cached = _title_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    title = None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:20000]
        meta, body = split_front_matter(text)
        title = meta.get("title") or (m.group(1).strip() if (m := _H1.search(body)) else None)
    except OSError:
        pass
    _title_cache[key] = (mtime, str(title) if title else None)
    return _title_cache[key][1]


# --- Albero ---------------------------------------------------------------
@dataclass
class Node:
    name: str
    path: str
    is_dir: bool
    kind: str
    title: str
    index: str | None = None  # per cartelle: percorso della pagina indice
    children: list["Node"] = field(default_factory=list)
    level: int = 0  # livello di accesso effettivo, impostato dai permessi


def _sort_key(p: Path):
    return (0 if p.is_dir() else 1, p.name.lower())


def build_tree(rel: str = "") -> Node:
    p = abs_path(rel)
    name = p.name if rel else ""
    node = Node(name=name, path=rel, is_dir=True, kind="folder", title=pretty(name) if rel else "Home")
    try:
        entries = sorted(p.iterdir(), key=_sort_key)
    except OSError:
        entries = []
    for child in entries:
        if child.name.startswith(".") or child.is_symlink():
            continue
        crel = f"{rel}/{child.name}" if rel else child.name
        if child.is_dir():
            node.children.append(build_tree(crel))
        elif child.is_file():
            kind = kind_of(child.name)
            if child.name in INDEX_NAMES and node.index is None:
                node.index = crel
                if rel and (t := md_title(child)):
                    node.title = t
                continue
            title = (md_title(child) if kind == "markdown" else None) or pretty(child.name)
            node.children.append(Node(name=child.name, path=crel, is_dir=False, kind=kind, title=title))
    return node


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name.strip()
    name = re.sub(r"[\x00-\x1f/]", "", name)
    if not name or name.startswith("."):
        raise PathError("Nome file non valido")
    return name[:200]


def ensure_dirs() -> None:
    for d in (settings.docs_dir, settings.branding_dir, settings.cache_dir):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:  # es. branding montato in sola lettura da una ConfigMap
            if not d.exists():
                raise


def remove(rel: str) -> None:
    p = abs_path(rel)
    if not rel:
        raise PathError("Impossibile eliminare la radice")
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
