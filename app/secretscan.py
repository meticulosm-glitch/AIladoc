"""Rilevamento di password e credenziali scritte nei documenti.

Due livelli, uno sopra l'altro:

1. **detect-secrets** (Yelp, Apache 2.0) per i formati con una struttura riconoscibile:
   chiavi AWS/Azure, token GitHub/GitLab/Slack/Stripe/OpenAI/npm/PyPI…, JWT, chiavi private,
   credenziali dentro un URL (``postgres://utente:password@host``). Usiamo solo questi
   rilevatori: quelli "a entropia" e quello generico per parole chiave sono pensati per il
   codice e sulla documentazione segnalano parole normali.

2. **Regole proprie** pensate per la documentazione scritta da persone, in italiano e inglese:
   - "Password: Estate2026!", "la password del wifi è Ciao1234", "pwd = …", "PIN: 4821",
     "chiave WPA: …", "API key: …", "Credenziali: admin / Pa55word";
   - tabelle Markdown e Word con una colonna "Password" / "PIN" / "Token"…;
   - fogli Excel/CSV con una colonna di password o con coppie "Password" | valore.
   I valori segnaposto (``****``, ``<password>``, ``${PASSWORD}``, "da richiedere"…) e le
   parole normali ("la password è obbligatoria") vengono ignorati.

Il valore trovato non viene mai salvato: si conservano una versione mascherata ("S•••••••!")
e un'impronta HMAC che serve a segnare i falsi positivi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets as _pysecrets
import threading
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

from . import storage
from .config import settings

log = logging.getLogger("ailadoc.secretscan")
SCANNER_VERSION = 1
MAX_FILE_MB = 50
MASK = "••••••"

# ----------------------------------------------------------------- detect-secrets
_DS_LABELS = {
    "AWS Access Key": "Chiave di accesso AWS",
    "Azure Storage Account access key": "Chiave di Azure Storage",
    "Basic Auth Credentials": "Credenziali in un URL",
    "GitHub Token": "Token GitHub",
    "GitLab Token": "Token GitLab",
    "JSON Web Token": "Token JWT",
    "Private Key": "Chiave privata",
    "Slack Token": "Token Slack",
    "Stripe Access Key": "Chiave Stripe",
    "Twilio API Key": "Chiave Twilio",
    "SendGrid API Key": "Chiave SendGrid",
    "NPM tokens": "Token npm",
    "PyPI Token": "Token PyPI",
    "OpenAI Token": "Chiave OpenAI",
    "Discord Bot Token": "Token Discord",
    "Telegram Bot Token": "Token Telegram",
    "Mailchimp Access Key": "Chiave Mailchimp",
}
_DS_SKIP = {"Base64HighEntropyString", "HexHighEntropyString", "KeywordDetector", "IPPublicDetector"}
_ds_lock = threading.Lock()
try:  # pragma: no branch
    from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class
    from detect_secrets.core.scan import scan_line as _ds_scan_line
    from detect_secrets.settings import get_settings as _ds_settings

    _ds_settings().configure_plugins([
        {"name": c.__name__} for c in get_mapping_from_secret_type_to_class().values() if c.__name__ not in _DS_SKIP
    ])
    DETECT_SECRETS = True
except Exception as e:  # noqa: BLE001 - senza libreria restano attive le regole proprie
    log.warning("detect-secrets non disponibile (%s): uso solo le regole interne", e)
    DETECT_SECRETS = False


# ------------------------------------------------------------------ regole proprie
_KW = (
    r"pass(?:word|wd|phrase|code|wort)?|pwd|psw|"
    r"parola\s+(?:chiave|d['’]ordine|segreta)|"
    r"chiave\s+(?:segreta|privata|di\s+accesso|di\s+rete|wi-?fi|wpa2?|api)|"
    r"codice\s+(?:di\s+accesso|segreto|pin|di\s+sblocco)|"
    r"pin|puk|wpa2?(?:[\s-]psk)?|psk|"
    r"(?:client[\s_-]?)?secret|segreto|"
    r"api[\s_-]?key|apikey|access[\s_-]?key|secret[\s_-]?key|private[\s_-]?key|"
    r"(?:auth|access|bearer|api|refresh)[\s_-]?token|token"
)
_KW_RE = re.compile(rf"(?<![\w-])(?P<kw>{_KW})(?![\w-])", re.I)
# fino a 5 parole tra la parola chiave e il separatore: "password del database di produzione:"
_FILLER = r"(?:[\s(]+[\w'’./()-]{1,24}){0,5}?"
_SEP = r"\s*(?:[:=]|=>|->|\s(?:è|e'|é|is|sono|vale|era)(?=\s))\s*:?\s*"
_VALUE = r"(?P<val>`[^`]{1,200}`|\"[^\"]{1,200}\"|'[^'\s][^']{0,199}'|«[^»]{1,200}»|[^\s|]{1,200})"
_ASSIGN_RE = re.compile(rf"(?<![\w-])(?P<kw>{_KW})(?![\w-]){_FILLER}{_SEP}{_VALUE}", re.I)
_CRED_RE = re.compile(
    r"(?<![\w-])(?P<kw>credenziali|credentials|login|utenza|account)(?![\w-])\s*(?:[:=]|è|sono)\s*"
    r"(?P<user>[^\s/:|,]{1,64})\s*(?:/|:|\||,|\s-\s)\s*(?P<val>[^\s|]{1,200})", re.I)
_URL_CRED_RE = re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://(?P<user>[^\s:/@'\"`]{1,64}):(?P<val>[^\s@/'\"`]{1,200})@[\w.-]", re.I)
_PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S)
_PLACEHOLDER = re.compile(
    r"^(?:x{3,}|\*{3,}|•{2,}|\.{2,}|…|-+|_+|\?+|#+|0{4,}|<[^>]*>|\[[^\]]*\]|\{\{.*\}\}|\{[\w.-]+\}|"
    r"\$\{?[\w.-]+\}?|%[\w.-]+%|\(.*\)|n/?a|tbd|todo|none|null|nil|empty|vuot[ao]|nessun[ao]?|"
    r"changeme|change[_-]?me|changeit|password\d?|passwd|pass|pwd|psw|pw|secret|segret[ao]|user|utente|your[_-]?(?:password|token|key|secret)|"
    r"(?:la[_-]?)?tua[_-]?password|example|esempio|redacted|omissis|personale|riservat[ao]|nascost[ao]|"
    r"obbligatori[ao]|richiest[ao]|da\s+\w+.*)$", re.I)
_STOP_VALUES = {"vedi", "see", "chiedi", "chiedere", "richiedi", "richiedila", "richiederla", "nel", "nella",
                "the", "your", "sul", "sulla", "presso", "tramite", "via", "come", "uguale", "stessa", "stesso",
                "dimenticata", "scaduta", "errata", "sbagliata", "temporanea", "iniziale", "nuova", "vecchia"}
_HEADER_KW = re.compile(rf"^\W*(?:{_KW})(?:\s+[\w'’]+){{0,3}}\W*$", re.I)
_EMPH = re.compile(r"\*\*|__|(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])")


def _category(kw: str) -> str:
    k = kw.lower()
    if k in ("pin", "puk") or k.startswith("codice"):
        return "pin"
    if "token" in k or "key" in k or "secret" in k or k in ("segreto",) or k.startswith("chiave") and "api" in k:
        return "token"
    return "password"


def _unquote(v: str) -> tuple[str, int]:
    """Toglie virgolette/backtick esterni. Ritorna (valore, spostamento iniziale)."""
    if len(v) >= 2 and v[0] in "`\"'«" and v[-1] in "`\"'»":
        return v[1:-1], 1
    stripped = v.rstrip(".,;:)]}>»\"'")
    return stripped, 0


def plausible(value: str, category: str = "password", relaxed: bool = False) -> bool:
    """Il valore sembra davvero un segreto (e non una parola, un segnaposto o un link)?"""
    v = value.strip()
    if not v or len(v) > 200 or _PLACEHOLDER.match(v) or v.lower() in _STOP_VALUES or v[0] in "([{<$":
        return False
    if re.match(r"^(?:https?://|www\.|mailto:|/|\\\\|[\w.+-]+@[\w-]+\.[\w.]+$)", v, re.I):
        return False
    if category == "pin":
        return bool(re.fullmatch(r"\d{4,10}", v)) and not (relaxed is False and re.fullmatch(r"(?:19|20)\d\d", v))
    if len(v) < 4:
        return False
    has_digit = any(c.isdigit() for c in v)
    has_alpha = any(c.isalpha() for c in v)
    has_symbol = any(not c.isalnum() and not c.isspace() for c in v)
    has_upper, has_lower = any(c.isupper() for c in v), any(c.islower() for c in v)
    if " " in v:  # frase tra virgolette: solo se lunga e non banale (in tabella è quasi sempre una descrizione)
        return not relaxed and len(v) >= 12 and (has_digit or has_symbol)
    if category == "token":
        return len(v) >= 12 and ((has_alpha and has_digit) or len(v) >= 20)
    if relaxed:  # colonna "Password" di una tabella: basta che non sia un segnaposto
        return len(v) >= 4
    if not has_digit and not has_symbol:  # solo lettere
        if v.islower() or (v[0].isupper() and v[1:].islower()) or (v.isupper() and len(v) <= 5):
            return False
        return len(v) >= 6 and has_upper and has_lower  # CamelCase tipo "MiaPassSegreta"
    if v.isdigit():
        return len(v) >= 6 or (len(v) >= 4 and not re.fullmatch(r"(?:19|20)\d\d", v))
    return True


def mask(value: str) -> str:
    v = value.strip()
    if len(v) >= 8:
        return v[0] + "•" * min(len(v) - 2, 10) + v[-1]
    return "•" * max(len(v), 4)


# ------------------------------------------------------------------------ risultati
@dataclass
class Finding:
    rule: str            # "password" | "pin" | "token" | "credentials" | "table" | "ds:<tipo>"
    label: str           # descrizione leggibile
    location: str        # "Riga 12", "Pagina 3", "Foglio Utenti, riga 4", "Tabella 1, riga 3"
    anchor: str = ""     # suffisso URL per aprire il punto giusto ("?page=3", "?sheet=Utenti")
    line: int | None = None
    masked: str = ""
    context: str = ""    # la riga con il valore mascherato
    fp: str = ""         # impronta HMAC del valore (per i falsi positivi)
    start: int = field(default=-1, repr=False)
    end: int = field(default=-1, repr=False)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("start"), d.pop("end")
        return d


_salt: bytes = b""


def set_salt(value: str) -> None:
    global _salt
    _salt = value.encode()


def fingerprint(value: str) -> str:
    return hmac.new(_salt or b"ailadoc", value.strip().encode(), hashlib.sha256).hexdigest()[:24]


def _context(line: str, start: int, end: int, masked: str, width: int = 140) -> str:
    text = line[:start] + masked + line[end:]
    m_start = start
    lo = max(0, m_start - width // 2)
    hi = min(len(text), lo + width)
    out = text[lo:hi].strip()
    return ("…" if lo > 0 else "") + out + ("…" if hi < len(text) else "")


def _make(rule: str, label: str, line: str, start: int, end: int, location: str, anchor: str,
          lineno: int | None) -> Finding:
    value = line[start:end]
    m = mask(value)
    return Finding(rule, label, location, anchor, lineno, m, _context(line, start, end, m), fingerprint(value), start, end)


# ---------------------------------------------------------------------- scansione
def scan_line(line: str, location: str = "", anchor: str = "", lineno: int | None = None) -> list[Finding]:
    """Trova i segreti in una riga (o in un breve paragrafo)."""
    if not line or len(line) > 20000:
        line = line[:20000]
    found: list[Finding] = []
    spans: list[tuple[int, int]] = []

    def add(rule, label, s, e):
        if e <= s or any(s < b and e > a for a, b in spans):
            return
        spans.append((s, e))
        found.append(_make(rule, label, line, s, e, location, anchor, lineno))

    # 1) detect-secrets: formati noti
    if DETECT_SECRETS:
        with _ds_lock:
            try:
                ds = list(_ds_scan_line(line))
            except Exception:  # noqa: BLE001
                ds = []
        for s in ds:
            val = s.secret_value or ""
            if not val or (s.type == "Basic Auth Credentials" and not plausible(val, relaxed=True)):
                continue
            i = line.find(val)
            if i < 0:
                continue
            a, b = i, i + len(val)
            if s.type in ("GitHub Token", "GitLab Token", "Slack Token", "Private Key"):
                if s.type == "Private Key":
                    a, b = 0, len(line)
                else:  # il rilevatore cattura solo il prefisso: estendi al token intero
                    while a > 0 and not line[a - 1].isspace() and line[a - 1] not in "\"'`(<[":
                        a -= 1
                    while b < len(line) and not line[b].isspace() and line[b] not in "\"'`)>],;":
                        b += 1
            add("ds:" + s.type, _DS_LABELS.get(s.type, s.type), a, b)

    # 2) regole proprie (su una copia senza enfasi Markdown, stessa lunghezza)
    clean = _EMPH.sub(lambda m: " " * len(m.group()), line)
    for m in _URL_CRED_RE.finditer(clean):
        if plausible(m.group("val"), relaxed=True):
            add("url", "Credenziali in un URL", m.start("val"), m.end("val"))
    for m in _CRED_RE.finditer(clean):
        val, off = _unquote(m.group("val"))
        if plausible(val):
            s = m.start("val") + off
            add("credentials", "Credenziali in chiaro", s, s + len(val))
    for m in _ASSIGN_RE.finditer(clean):
        cat = _category(m.group("kw"))
        val, off = _unquote(m.group("val"))
        if val.lower().rstrip(":") == m.group("kw").lower():
            continue
        if plausible(val, cat):
            s = m.start("val") + off
            label = {"pin": "PIN o codice in chiaro", "token": "Chiave o token in chiaro"}.get(cat, "Password in chiaro")
            add(cat, label, s, s + len(val))
    return found


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _table_findings(rows: list[list[str]], loc_prefix: str, anchor: str, line_numbers: list[int] | None = None,
                    header_row: int = 0) -> list[Finding]:
    """Tabelle: colonne con intestazione "Password"/"PIN"/... e coppie orizzontali "Password" | valore."""
    out: list[Finding] = []
    if not rows:
        return out
    header = [str(c or "").strip() for c in rows[header_row]]
    cols = {j: _category(_KW_RE.search(h).group("kw")) for j, h in enumerate(header) if h and _HEADER_KW.match(h)}
    for i, row in enumerate(rows):
        cells = [str(c or "").strip() for c in row]
        lineno = line_numbers[i] if line_numbers else None
        loc = _cap(f"{loc_prefix}riga {lineno if lineno else i + 1}")
        line_text = " | ".join(cells)
        offsets, pos = [], 0
        for c in cells:
            offsets.append(pos)
            pos += len(c) + 3
        if i > header_row:
            for j, cat in cols.items():
                if j < len(cells):
                    val, off = _unquote(cells[j])
                    if plausible(val, cat, relaxed=True):
                        s = offsets[j] + off
                        out.append(_make("table", "Password in una tabella", line_text, s, s + len(val), loc, anchor, lineno))
        for j, c in enumerate(cells[:-1]):  # coppia orizzontale: | Password | Xy7! |
            if c and _HEADER_KW.match(c):
                k = j + 1
                while k < len(cells) and not cells[k]:
                    k += 1
                if k < len(cells) and not _HEADER_KW.match(cells[k]):
                    val, off = _unquote(cells[k])
                    cat = _category(_KW_RE.search(c).group("kw"))
                    # nella riga d'intestazione "Password | Note" non è una coppia: lì serve il controllo rigoroso
                    ok = plausible(val, cat, relaxed=(i != header_row))
                    if ok and not any(f.start == offsets[k] + off and f.line == lineno for f in out):
                        s = offsets[k] + off
                        out.append(_make("table", "Password in una tabella", line_text, s, s + len(val), loc, anchor, lineno))
    return out


_MD_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_MD_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def scan_text(text: str, location_prefix: str = "Riga ", anchor: str = "") -> list[Finding]:
    """Testo riga per riga (Markdown, file di testo): regole, tabelle Markdown, chiavi PEM."""
    lines = text.split("\n")
    out: list[Finding] = []
    for i, line in enumerate(lines, start=1):
        out += scan_line(line, f"{location_prefix}{i}", anchor, i)
    # tabelle Markdown
    i = 0
    while i < len(lines):
        if _MD_ROW.match(lines[i]) and i + 1 < len(lines) and _MD_SEP.match(lines[i + 1]):
            start = i
            rows, nums = [], []
            j = i
            while j < len(lines) and (_MD_ROW.match(lines[j]) or (j == start + 1 and _MD_SEP.match(lines[j]))):
                if j != start + 1:
                    rows.append([c.strip() for c in _MD_ROW.match(lines[j]).group(1).split("|")])
                    nums.append(j + 1)
                j += 1
            for f in _table_findings(rows, "Riga ", anchor, nums)[:]:
                if not any(g.line == f.line and g.fp == f.fp for g in out):
                    f.location = f"Riga {f.line}"
                    out.append(f)
            i = j
        else:
            i += 1
    return out


def _docx_tables(p: Path) -> list[list[list[str]]]:
    with zipfile.ZipFile(p) as z:
        if "word/document.xml" not in z.namelist():
            return []
        root = ET.fromstring(z.read("word/document.xml"))
    tables = []
    for tbl in (el for el in root.iter() if el.tag.endswith("}tbl")):
        rows = []
        for tr in (el for el in tbl if el.tag.endswith("}tr")):
            cells = []
            for tc in (el for el in tr if el.tag.endswith("}tc")):
                cells.append(" ".join(t.text for t in tc.iter() if t.tag.endswith("}t") and t.text).strip())
            rows.append(cells)
        tables.append(rows)
    return tables


def scan_file(p: Path) -> list[Finding]:
    """Trova i segreti in un file della documentazione."""
    try:
        if p.stat().st_size > MAX_FILE_MB * 1024 * 1024:
            return []
    except OSError:
        return []
    kind = storage.kind_of(p.name)
    ext = p.suffix.lower().lstrip(".")
    out: list[Finding] = []
    try:
        if kind in ("markdown", "text"):
            return scan_text(p.read_text(encoding="utf-8", errors="replace"))
        if ext in ("xlsx", "xlsm", "csv", "tsv"):
            from .preview import sheet_tables

            tables = sheet_tables(p)
            multi = len(tables) > 1
            for t in tables:
                anchor = f"?sheet={quote(t['name'])}" if multi else ""
                prefix = f"Foglio {t['name']}, " if multi else ""
                rows = t["rows"]
                out += _table_findings(rows, prefix, anchor)
                for i, row in enumerate(rows, start=1):
                    for c in row:
                        c = str(c or "")
                        if c:
                            out += scan_line(c, _cap(f"{prefix}riga {i}"), anchor, i)
            return _dedupe(out)
        if ext in ("docx", "docm", "dotx"):
            for n, rows in enumerate(_docx_tables(p), start=1):
                out += _table_findings(rows, f"Tabella {n}, ", "")
        from .assistant import extract  # estrazione di PDF, Word, PowerPoint, OpenDocument

        for psg in extract(p):
            for f in scan_line(psg.text, psg.loc or "Testo", psg.anchor):
                out.append(f)
    except Exception as e:  # noqa: BLE001 - un file illeggibile non deve fermare la scansione
        log.info("Controllo password non riuscito su %s: %s", p.name, e)
    return _dedupe(out)


def _dedupe(items: list[Finding]) -> list[Finding]:
    seen, out = set(), []
    for f in items:
        key = (f.fp, f.location)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def redact(text: str) -> str:
    """Sostituisce i segreti trovati con •••••• (per estratti, ricerca e assistente)."""
    if not text or not settings.secrets_scan:
        return text
    text = _PEM_RE.sub("-----PRIVATE KEY " + MASK + "-----", text)
    out_lines = []
    for line in text.split("\n"):
        fs = sorted(scan_line(line), key=lambda f: f.start, reverse=True)
        for f in fs:
            line = line[:f.start] + MASK + line[f.end:]
        out_lines.append(line)
    return "\n".join(out_lines)


# ------------------------------------------------------------------- registro
class Registry:
    """Risultati per file, aggiornati quando i file cambiano. Persistiti senza i valori in chiaro."""

    def __init__(self) -> None:
        self.docs: dict[str, tuple[str, list[Finding]]] = {}
        self.ignored: set[tuple[str, str]] = set()  # (path, fp)
        self._lock = threading.Lock()
        self._last = 0.0
        self.last_full_scan: float = 0.0
        self._loaded = False

    def _cache_file(self) -> Path:
        return settings.cache_dir / "secrets.json"

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads(self._cache_file().read_text(encoding="utf-8"))
            if data.get("version") == SCANNER_VERSION:
                self.docs = {rel: (v["sig"], [Finding(**f) for f in v["findings"]]) for rel, v in data["docs"].items()}
        except (OSError, ValueError, TypeError, KeyError):
            self.docs = {}

    def _save(self) -> None:
        try:
            data = {"version": SCANNER_VERSION, "docs": {
                rel: {"sig": sig, "findings": [f.public() for f in fs]} for rel, (sig, fs) in self.docs.items()}}
            tmp = self._cache_file().with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._cache_file())
        except OSError as e:
            log.warning("Impossibile salvare la cache del controllo password: %s", e)

    @staticmethod
    def _walk() -> dict[str, tuple[Path, str]]:
        root = settings.docs_dir.resolve()
        found: dict[str, tuple[Path, str]] = {}
        if not root.is_dir():
            return found
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                fp = Path(dirpath) / fn
                if fp.is_symlink():
                    continue
                try:
                    st = fp.stat()
                except OSError:
                    continue
                found[fp.relative_to(root).as_posix()] = (fp, f"{st.st_mtime_ns}-{st.st_size}")
        return found

    def refresh(self, force: bool = False, wait: bool = True) -> None:
        """Ricontrolla i file cambiati. wait=False: se un controllo è già in corso non aspetta."""
        if not settings.secrets_scan:
            return
        now = time.monotonic()
        if not force and now - self._last < settings.secrets_rescan_seconds:
            return
        if not self._lock.acquire(blocking=wait):
            return
        try:
            self._load()
            found = self._walk()
            changed = False
            for rel in list(self.docs):
                if rel not in found:
                    del self.docs[rel]
                    changed = True
            for rel, (fp, sig) in found.items():
                cur = self.docs.get(rel)
                if cur and cur[0] == sig:
                    continue
                self.docs[rel] = (sig, [f for f in scan_file(fp)])
                changed = True
            if changed:
                self._save()
            self._last = time.monotonic()
            self.last_full_scan = time.time()
        finally:
            self._lock.release()

    def rescan(self, rel: str) -> list[Finding]:
        """Ricontrolla subito un file (dopo un salvataggio o un upload)."""
        if not settings.secrets_scan:
            return []
        p = storage.abs_path(rel)
        with self._lock:
            self._load()
            if not p.is_file():
                self.docs.pop(rel, None)
                self._save()
                return []
            st = p.stat()
            fs = scan_file(p)
            self.docs[rel] = (f"{st.st_mtime_ns}-{st.st_size}", fs)
            self._save()
        return self.findings(rel)

    def forget(self, prefix: str) -> None:
        with self._lock:
            for rel in [r for r in self.docs if r == prefix or r.startswith(prefix + "/")]:
                del self.docs[rel]
            self._save()

    def set_ignored(self, pairs: set[tuple[str, str]]) -> None:
        self.ignored = set(pairs)

    def _visible(self, rel: str, fs: list[Finding]) -> list[Finding]:
        return [f for f in fs if (rel, f.fp) not in self.ignored and ("*", f.fp) not in self.ignored]

    def findings(self, rel: str) -> list[Finding]:
        entry = self.docs.get(rel)
        return self._visible(rel, entry[1]) if entry else []

    def all(self) -> dict[str, list[Finding]]:
        return {rel: v for rel, (_, fs) in sorted(self.docs.items()) if (v := self._visible(rel, fs))}

    def count(self) -> int:
        return sum(len(v) for v in self.all().values())


SCANNER = Registry()


def new_salt() -> str:
    return _pysecrets.token_hex(32)
