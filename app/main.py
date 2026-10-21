"""AIladoc - visualizzatore di documentazione con accesso basato su ruoli Keycloak."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import mimetypes
import secrets
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from . import assistant, auth, creator, db as dbm, preview, secretscan, storage
from .config import settings
from .db import (LEVEL_LABELS, LEVELS, PRINCIPAL_TYPES, AclEntry, AppRole, GroupMember, LocalGroup, Restriction,
                 SecretIgnore, get_db)
from .icons import icon, kind_icon
from .permissions import ADMIN, EDIT, NONE, VIEW, Perms, UserCtx, resolve_user
from .render import pygments_css, render_markdown
from .storage import KIND_LABELS, PathError

log = logging.getLogger("ailadoc")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
APP_DIR = Path(__file__).parent
LOGO_EXTS = ("svg", "png", "webp", "jpg", "jpeg")
LOGO_KINDS = {"app": "app-logo", "company": "company-logo"}


# --------------------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(_app):
    storage.ensure_dirs()
    dbm.init_db()
    samples = APP_DIR.parent / "sample-docs"
    if settings.seed_sample_docs and samples.is_dir() and not any(settings.docs_dir.iterdir()):
        shutil.copytree(samples, settings.docs_dir, dirs_exist_ok=True)
        log.info("Copiati i documenti di esempio in %s", settings.docs_dir)
    secretscan.set_salt(dbm.get_or_create_setting("secretscan_salt", secretscan.new_salt))
    _reload_secret_ignores()
    assistant.purge_unredacted_cache()
    if settings.secrets_scan:  # controllo password su tutti i documenti, in background
        threading.Thread(target=secretscan.SCANNER.refresh, kwargs={"force": True}, daemon=True,
                         name="secret-scan").start()
    if settings.assistant_enabled:  # prepara l'indice dell'assistente senza bloccare l'avvio
        threading.Thread(target=assistant.INDEX.refresh, kwargs={"force": True}, daemon=True,
                         name="assistant-index").start()
        log.info("Assistente %s attivo (LLM: %s)", settings.assistant_name, assistant.llm_provider())
    if settings.dev_auth:
        log.warning("AUTH_DEV_MODE attivo: login senza Keycloak. NON usare in produzione!")
    if not settings.oidc_client_secret and not settings.dev_auth:
        log.info("OIDC_CLIENT_SECRET vuoto: uso client pubblico con PKCE.")
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware, secret_key=settings.secret_key, session_cookie="ailadoc_session",
    max_age=settings.session_max_age, same_site="lax", https_only=settings.cookie_secure,
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals.update(
    icon=icon, kind_icon=kind_icon, settings=settings, KIND_LABELS=KIND_LABELS, LEVEL_LABELS=LEVEL_LABELS,
    PRINCIPAL_TYPES=PRINCIPAL_TYPES, quote=quote, assistant_ai=lambda: assistant.llm_provider() != "none",
)
templates.env.filters["urlpath"] = lambda p: quote(p or "")


# ------------------------------------------------------------------- eccezioni
class NeedLogin(Exception):
    pass


class Denied(Exception):
    def __init__(self, reason: str = "app", path: str = ""):
        self.reason, self.path = reason, path


class NotFound(Exception):
    pass


@app.exception_handler(NeedLogin)
async def _need_login(request: Request, _exc):
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(nxt)}", status_code=303)


@app.exception_handler(Denied)
async def _denied(request: Request, exc: Denied):
    user = getattr(request.state, "user", None)
    perms = getattr(request.state, "perms", None)
    tree = perms.filter_tree(storage.build_tree()) if (perms and user and user.global_level > NONE) else None
    return render(request, "deny.html", {"reason": exc.reason, "path": exc.path, "tree": tree}, status=403)


@app.exception_handler(NotFound)
@app.exception_handler(PathError)
async def _not_found(request: Request, _exc):
    user = getattr(request.state, "user", None)
    perms = getattr(request.state, "perms", None)
    tree = perms.filter_tree(storage.build_tree()) if (perms and user and user.global_level > NONE) else None
    return render(request, "notfound.html", {"tree": tree}, status=404)


# ---------------------------------------------------------------- dipendenze
def get_perms(request: Request, db: Session = Depends(get_db)) -> Perms:
    su = request.session.get("user")
    if not su:
        raise NeedLogin()
    user = resolve_user(db, su)
    perms = Perms(db, user)
    request.state.user, request.state.perms = user, perms
    if user.global_level <= NONE:
        raise Denied("app")
    return perms


def get_admin(perms: Perms = Depends(get_perms)) -> Perms:
    if not perms.user.is_admin:
        raise Denied("admin")
    return perms


async def check_csrf(request: Request) -> None:
    token = request.headers.get("x-csrf-token")
    if not token:
        form = await request.form()
        token = form.get("csrf")
    expected = request.session.get("csrf")
    if not expected or not token or not secrets.compare_digest(str(token), expected):
        raise Denied("csrf")


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]


def flash(request: Request, msg: str, kind: str = "ok") -> None:
    request.session.setdefault("flash", []).append([kind, msg])


def logo_file(which: str) -> Path | None:
    base = LOGO_KINDS[which]
    for ext in LOGO_EXTS:
        p = settings.branding_dir / f"{base}.{ext}"
        if p.exists():
            return p
    return None


def logo_url(which: str) -> str | None:
    p = logo_file(which)
    if p is None:
        return "/static/img/app-logo-default.svg" if which == "app" else None
    return f"/branding/{which}?v={int(p.stat().st_mtime)}"


def _reload_secret_ignores() -> None:
    with dbm.SessionLocal() as db:
        secretscan.SCANNER.set_ignored({(i.path, i.fp) for i in db.scalars(select(SecretIgnore))})


def secret_findings(rel: str) -> list:
    if not settings.secrets_scan:
        return []
    secretscan.SCANNER.refresh(wait=False)
    return secretscan.SCANNER.findings(rel)


def render(request: Request, name: str, ctx: dict | None = None, status: int = 200) -> HTMLResponse:
    ctx = dict(ctx or {})
    ctx.setdefault("user", getattr(request.state, "user", None))
    ctx.setdefault("current", "")
    ctx.setdefault("tree", None)
    ctx["csrf"] = csrf_token(request)
    ctx["flashes"] = request.session.pop("flash", [])
    ctx["app_logo"] = logo_url("app")
    ctx["company_logo"] = logo_url("company")
    ctx["open_paths"] = set(storage.ancestors(ctx["current"])) if ctx["current"] else {""}
    perms = getattr(request.state, "perms", None)
    ctx["restricted_set"] = set(perms.restrictions) if (perms and perms.user.is_admin) else set()
    # cartella proposta di default nel dialogo "Nuovo"
    parent = ctx["current"]
    try:
        if parent and not storage.abs_path(parent).is_dir():
            parent = storage.parent_of(parent)
    except PathError:
        parent = ""
    ctx["create_parent"] = parent
    ctx["secret_set"], ctx["secret_count"] = set(), 0
    if settings.secrets_scan and perms and perms.user.is_admin:
        secretscan.SCANNER.refresh(wait=False)
        found = secretscan.SCANNER.all()
        ctx["secret_set"], ctx["secret_count"] = set(found), sum(len(v) for v in found.values())
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def breadcrumbs(rel: str, last_title: str | None = None) -> list[tuple[str, str]]:
    crumbs, acc = [], ""
    for seg in [s for s in rel.split("/") if s]:
        acc = f"{acc}/{seg}" if acc else seg
        p = storage.abs_path(acc)
        title = None
        if p.is_dir():
            idx = next((p / n for n in storage.INDEX_NAMES if (p / n).is_file()), None)
            title = storage.md_title(idx) if idx else None
        crumbs.append((title or storage.pretty(seg), acc))
    if crumbs and last_title:
        crumbs[-1] = (last_title, crumbs[-1][1])
    return crumbs


def find_node(tree: storage.Node, rel: str) -> storage.Node | None:
    if tree.path == rel:
        return tree
    for c in tree.children:
        if c.path == rel or (c.is_dir and rel.startswith(c.path + "/")):
            if (n := find_node(c, rel)) is not None:
                return n
    return None


def fmt_time(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")


# ----------------------------------------------------------------- pubbliche
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


@app.get("/assets/pygments.css", include_in_schema=False)
async def pyg_css():
    return Response(pygments_css(), media_type="text/css", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/branding/{which}", include_in_schema=False)
async def branding(which: str):
    if which not in LOGO_KINDS or (p := logo_file(which)) is None:
        return Response(status_code=404)
    headers = {"Cache-Control": "public, max-age=31536000"}
    if p.suffix == ".svg":
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return FileResponse(p, headers=headers)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    p = logo_file("app")
    return FileResponse(p) if p else FileResponse(APP_DIR / "static/img/app-logo-default.svg", media_type="image/svg+xml")


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request, next: str = "/"):
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    if settings.dev_auth:
        return render(request, "dev_login.html", {"next": next})
    return RedirectResponse(auth.build_login_redirect(request.session, next), status_code=303)


DEV_PRESETS = {
    "admin": ("Anna Admin", ["ailadoc-admin"]),
    "editor": ("Elio Editor", ["ailadoc-editor"]),
    "viewer": ("Vera Viewer", ["ailadoc-viewer"]),
    "nobody": ("Nino Nessuno", []),
}


@app.post("/dev-login")
async def dev_login(request: Request, username: str = Form(...), roles: str = Form(""), next: str = Form("/")):
    if not settings.dev_auth:
        return Response(status_code=404)
    name = DEV_PRESETS.get(username, (username, []))[0]
    request.session.clear()
    request.session["user"] = {
        "sub": f"dev-{username}", "username": username, "email": f"{username}@example.com", "name": name,
        "roles": sorted({r.strip() for r in roles.split(",") if r.strip()}), "dev": True,
    }
    return RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)


@app.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return render(request, "error.html", {"message": f"Keycloak: {error_description or error}"}, status=400)
    try:
        user, nxt, id_token = await auth.handle_callback(request.session, code, state)
    except auth.AuthError as e:
        return render(request, "error.html", {"message": str(e)}, status=400)
    except Exception:  # noqa: BLE001
        log.exception("Errore nel callback OIDC")
        return render(request, "error.html", {"message": "Impossibile contattare Keycloak."}, status=502)
    request.session.clear()
    request.session["user"] = user
    if len(id_token) < 2500:  # resta nel cookie di sessione (limite ~4 KB)
        request.session["idt"] = id_token
    return RedirectResponse(nxt, status_code=303)


@app.get("/logout")
async def logout(request: Request):
    was_dev = (request.session.get("user") or {}).get("dev")
    id_token = request.session.get("idt")
    request.session.clear()
    if settings.dev_auth or was_dev:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse(auth.build_logout_redirect(id_token), status_code=303)


# ------------------------------------------------------------------ documenti
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, perms: Perms = Depends(get_perms)):
    tree = perms.filter_tree(storage.build_tree())
    if tree.index and perms.can_view(tree.index):
        return await _render_md(request, perms, tree, tree.index, folder="")
    return render(request, "folder.html", {
        "tree": tree, "node": tree, "current": "", "crumbs": [], "can_edit": perms.can_edit(""),
        "is_home": True,
    })


@app.get("/d/{rel:path}", response_class=HTMLResponse)
async def view(request: Request, rel: str, perms: Perms = Depends(get_perms)):
    rel = storage.clean_rel(rel)
    p = storage.abs_path(rel)
    if not p.exists():
        raise NotFound()
    tree = perms.filter_tree(storage.build_tree())
    if p.is_dir():
        node = find_node(tree, rel)
        if node is None:
            raise Denied("doc", rel)
        if node.index:
            return await _render_md(request, perms, tree, node.index, folder=rel)
        return render(request, "folder.html", {
            "tree": tree, "node": node, "current": rel, "crumbs": breadcrumbs(rel),
            "can_edit": perms.can_edit(rel),
        })
    if not perms.can_view(rel):
        raise Denied("doc", rel)
    kind = storage.kind_of(p.name)
    if kind == "markdown":
        return await _render_md(request, perms, tree, rel)
    return await _render_file(request, perms, tree, rel, p, kind)


async def _render_md(request: Request, perms: Perms, tree, rel: str, folder: str | None = None):
    p = storage.abs_path(rel)
    text = p.read_text(encoding="utf-8", errors="replace")
    html, toc, meta = render_markdown(text, rel)
    current = folder if folder is not None else rel
    title = storage.md_title(p) or storage.pretty(p.name)
    return render(request, "doc.html", {
        "tree": tree, "current": current, "rel": rel, "html": html, "toc": toc, "meta": meta,
        "crumbs": breadcrumbs(current, title if folder is None else None), "can_edit": perms.can_edit(rel),
        "can_edit_folder": perms.can_edit(folder) if folder is not None else False,
        "folder": folder, "modified": fmt_time(p.stat().st_mtime),
        "restricted": perms.governing(rel), "title": title,
        "secrets": secret_findings(rel) if perms.can_edit(rel) else [],
    })


async def _render_file(request: Request, perms: Perms, tree, rel: str, p: Path, kind: str):
    st = p.stat()
    ctx = {
        "tree": tree, "current": rel, "rel": rel, "kind": kind, "name": p.name, "size": storage.human_size(st.st_size),
        "modified": fmt_time(st.st_mtime), "crumbs": breadcrumbs(rel, storage.pretty(p.name)), "can_edit": perms.can_edit(rel),
        "restricted": perms.governing(rel), "sheets": None, "text": None,
        "pdf_preview": preview.can_pdf_preview(p.name), "title": storage.pretty(p.name),
        "page": _int_param(request.query_params.get("page")), "sheet": request.query_params.get("sheet", ""),
        "secrets": secret_findings(rel) if perms.can_edit(rel) else [],
    }
    ext = p.suffix.lower().lstrip(".")
    if kind == "sheet" and ext in ("xlsx", "xlsm", "csv", "tsv"):
        try:
            ctx["sheets"] = await asyncio.to_thread(preview.sheet_tables, p)
        except Exception as e:  # noqa: BLE001
            log.warning("Lettura foglio fallita %s: %s", p, e)
    elif kind == "text" and st.st_size < 512 * 1024:
        ctx["text"] = p.read_text(encoding="utf-8", errors="replace")
    return render(request, "file.html", ctx)


def _int_param(v: str | None) -> int | None:
    try:
        n = int(v or "")
    except ValueError:
        return None
    return n if 0 < n < 100000 else None


def _serve(p: Path, attachment: bool) -> FileResponse:
    mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    if storage.kind_of(p.name) == "text":
        mt = "text/plain; charset=utf-8"
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=60"}
    if mt in ("image/svg+xml", "text/html", "application/xhtml+xml", "text/xml", "application/xml"):
        headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"
    disp = "attachment" if attachment else "inline"
    headers["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(p.name)}"
    return FileResponse(p, media_type=mt, headers=headers)


@app.get("/raw/{rel:path}")
async def raw(rel: str, perms: Perms = Depends(get_perms)):
    rel = storage.clean_rel(rel)
    p = storage.abs_path(rel)
    if not p.is_file():
        raise NotFound()
    if not perms.can_view(rel):
        raise Denied("doc", rel)
    return _serve(p, attachment=False)


@app.get("/download/{rel:path}")
async def download(rel: str, perms: Perms = Depends(get_perms)):
    rel = storage.clean_rel(rel)
    p = storage.abs_path(rel)
    if not p.is_file():
        raise NotFound()
    if not perms.can_view(rel):
        raise Denied("doc", rel)
    return _serve(p, attachment=True)


@app.get("/preview/{rel:path}")
async def office_preview(rel: str, perms: Perms = Depends(get_perms)):
    rel = storage.clean_rel(rel)
    p = storage.abs_path(rel)
    if not p.is_file():
        raise NotFound()
    if not perms.can_view(rel):
        raise Denied("doc", rel)
    pdf = await asyncio.to_thread(preview.office_to_pdf, p)
    if pdf is None:
        return PlainTextResponse("Anteprima non disponibile per questo file.", status_code=422)
    return FileResponse(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(p.stem + '.pdf')}",
        "Cache-Control": "private, max-age=300",
    })


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", perms: Perms = Depends(get_perms)):
    tree = perms.filter_tree(storage.build_tree())
    q = q.strip()
    results = []
    if len(q) >= 2:
        ql = q.lower()

        def walk(n: storage.Node):
            items = ([n.index] if n.index else []) + [c.path for c in n.children if not c.is_dir]
            for path in items:
                if path is None or not perms.can_view(path):
                    continue
                fp = storage.abs_path(path)
                title = (storage.md_title(fp) if fp.suffix.lower() in (".md", ".markdown") else None) or storage.pretty(fp.name)
                snippet, score = "", 0
                if ql in title.lower() or ql in fp.name.lower():
                    score += 10
                if storage.kind_of(fp.name) in ("markdown", "text"):
                    try:
                        body = fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        body = ""
                    idx = body.lower().find(ql)
                    if idx >= 0:
                        score += 1 + body.lower().count(ql)
                        s = max(0, idx - 80)
                        snippet = ("…" if s else "") + body[s: idx + len(q) + 120].replace("\n", " ") + "…"
                        snippet = secretscan.redact(snippet)
                if score:
                    results.append({"path": path, "title": title, "kind": storage.kind_of(fp.name),
                                    "snippet": snippet, "score": score, "crumbs": breadcrumbs(storage.parent_of(path))})
            for c in n.children:
                if c.is_dir:
                    walk(c)

        await asyncio.to_thread(walk, tree)
        results.sort(key=lambda r: -r["score"])
    return render(request, "search.html", {"tree": tree, "q": q, "results": results[:100]})


# ---------------------------------------------------------------- assistente
@app.post("/api/assistant", dependencies=[Depends(check_csrf)])
async def api_assistant(request: Request, perms: Perms = Depends(get_perms)):
    if not settings.assistant_enabled:
        raise NotFound()
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JSONResponse({"error": "Richiesta non valida."}, status_code=400)
    question = str(data.get("question", "")).strip()
    if not question:
        return JSONResponse({"error": "Scrivi una domanda."}, status_code=400)
    raw_history = data.get("history") if isinstance(data.get("history"), list) else []
    history = [{"role": str(h.get("role", "")), "content": str(h.get("content", ""))}
               for h in raw_history[-10:] if isinstance(h, dict)]
    if not assistant.allow_request(perms.user.sub or perms.user.username):
        return JSONResponse({"error": "Troppe domande in poco tempo: riprova tra un minuto."}, status_code=429)
    result = await asyncio.to_thread(assistant.answer, question, history, perms.can_view,
                                     perms.user.name or perms.user.username)
    log.info("Assistente: %s ha chiesto %r -> %d fonti (%s)", perms.user.username, question[:120],
             len(result["sources"]), result["mode"])
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/me", response_class=HTMLResponse)
async def me(request: Request, db: Session = Depends(get_db)):
    su = request.session.get("user")
    if not su:
        raise NeedLogin()
    user = resolve_user(db, su)
    request.state.user = user
    perms = Perms(db, user)
    tree = perms.filter_tree(storage.build_tree()) if user.global_level > NONE else None
    level_name = next((k for k, v in LEVELS.items() if v == user.global_level), "none")
    return render(request, "me.html", {"tree": tree, "level_name": level_name})


# -------------------------------------------------------------- modifica
def _require_edit(perms: Perms, rel: str) -> None:
    if not perms.can_edit(rel):
        raise Denied("edit", rel)


@app.get("/edit/{rel:path}", response_class=HTMLResponse)
async def edit_form(request: Request, rel: str, perms: Perms = Depends(get_perms)):
    rel = storage.clean_rel(rel)
    p = storage.abs_path(rel)
    if not p.is_file() or storage.kind_of(p.name) != "markdown":
        raise NotFound()
    _require_edit(perms, rel)
    tree = perms.filter_tree(storage.build_tree())
    content = p.read_text(encoding="utf-8", errors="replace")
    return render(request, "edit.html", {
        "tree": tree, "current": rel, "rel": rel, "content": content,
        "crumbs": breadcrumbs(rel), "is_new": False, "folder": storage.parent_of(rel), "filename": p.name,
        "mtime": p.stat().st_mtime_ns, "secrets": _check_text(content, rel),
    })


def _check_text(content: str, rel: str) -> list:
    if not settings.secrets_scan:
        return []
    fs = secretscan.scan_text(content)
    ign = secretscan.SCANNER.ignored
    return [f for f in fs if (rel, f.fp) not in ign and ("*", f.fp) not in ign]


def _secrets_gate(request: Request, perms: Perms, content: str, rel: str, confirmed: bool, ctx: dict):
    """None se si può salvare; altrimenti la pagina dell'editor con l'avviso (il testo non viene perso)."""
    found = _check_text(content, rel)
    if not found or (settings.secrets_policy != "block" and confirmed):
        return None
    tree = perms.filter_tree(storage.build_tree())
    msg = ("Il testo contiene password o credenziali: toglile prima di salvare." if settings.secrets_policy == "block"
           else "Il testo sembra contenere password o credenziali. Controlla e, se sei sicuro, salva comunque.")
    return render(request, "edit.html", {"tree": tree, "content": content, "secrets": found, "secret_msg": msg,
                                         "crumbs": breadcrumbs(ctx.get("folder") or ""), **ctx}, status=422)


@app.post("/edit/{rel:path}", dependencies=[Depends(check_csrf)])
async def edit_save(request: Request, rel: str, content: str = Form(""), mtime: str = Form(""),
                    confirm_secrets: str = Form(""), perms: Perms = Depends(get_perms)):
    rel = storage.clean_rel(rel)
    p = storage.abs_path(rel)
    if not p.is_file():
        raise NotFound()
    _require_edit(perms, rel)
    content = content.replace("\r\n", "\n")
    gate = _secrets_gate(request, perms, content, rel, bool(confirm_secrets), {
        "current": rel, "rel": rel, "is_new": False, "folder": storage.parent_of(rel), "filename": p.name,
        "mtime": mtime})
    if gate is not None:
        return gate
    if mtime and str(p.stat().st_mtime_ns) != mtime:
        flash(request, "Attenzione: il file era stato modificato da qualcun altro nel frattempo. "
                       "Hai sovrascritto quella versione.", "warn")
    p.write_text(content, encoding="utf-8")
    log.info("%s ha modificato %s", perms.user.username, rel)
    found = secretscan.SCANNER.rescan(rel)
    if found:
        log.warning("%s ha salvato %s con %d possibili password", perms.user.username, rel, len(found))
        flash(request, f"Pagina salvata, ma contiene {len(found)} possibili password o credenziali.", "warn")
    else:
        flash(request, "Pagina salvata.")
    return RedirectResponse(f"/d/{quote(rel)}", status_code=303)


@app.get("/new", response_class=HTMLResponse)
async def new_form(request: Request, dir: str = "", perms: Perms = Depends(get_perms)):
    folder = storage.clean_rel(dir)
    _require_edit(perms, folder)
    tree = perms.filter_tree(storage.build_tree())
    return render(request, "edit.html", {
        "tree": tree, "current": folder, "rel": "", "content": "# Nuova pagina\n\n", "crumbs": breadcrumbs(folder),
        "is_new": True, "folder": folder, "filename": "", "mtime": "",
    })


@app.post("/new", dependencies=[Depends(check_csrf)])
async def new_save(request: Request, folder: str = Form(""), filename: str = Form(...), content: str = Form(""),
                   confirm_secrets: str = Form(""), perms: Perms = Depends(get_perms)):
    folder = storage.clean_rel(folder)
    _require_edit(perms, folder)
    name = storage.safe_filename(filename)
    if not name.lower().endswith((".md", ".markdown")):
        name += ".md"
    rel = f"{folder}/{name}" if folder else name
    p = storage.abs_path(rel)
    if p.exists():
        flash(request, f"Esiste già un file chiamato «{name}».", "error")
        return RedirectResponse(f"/new?dir={quote(folder)}", status_code=303)
    content = content.replace("\r\n", "\n")
    gate = _secrets_gate(request, perms, content, rel, bool(confirm_secrets), {
        "current": folder, "rel": "", "is_new": True, "folder": folder, "filename": filename, "mtime": ""})
    if gate is not None:
        return gate
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    found = secretscan.SCANNER.rescan(rel)
    flash(request, f"Pagina creata, ma contiene {len(found)} possibili password o credenziali." if found
          else "Pagina creata.", "warn" if found else "ok")
    return RedirectResponse(f"/d/{quote(rel)}", status_code=303)


@app.post("/api/render", dependencies=[Depends(check_csrf)])
async def api_render(request: Request, perms: Perms = Depends(get_perms)):
    if not perms.user.can_edit:
        raise Denied("edit")
    data = await request.json()
    html, _, _ = render_markdown(str(data.get("content", "")), storage.clean_rel(str(data.get("path", ""))))
    return JSONResponse({"html": html})


@app.post("/api/secrets/check", dependencies=[Depends(check_csrf)])
async def api_secrets_check(request: Request, perms: Perms = Depends(get_perms)):
    """Controllo dal vivo nell'editor: ritorna le possibili password (mascherate) del testo."""
    if not perms.user.can_edit:
        raise Denied("edit")
    data = await request.json()
    rel = storage.clean_rel(str(data.get("path", "")))
    found = await asyncio.to_thread(_check_text, str(data.get("content", ""))[:2_000_000], rel)
    return JSONResponse({"enabled": settings.secrets_scan, "policy": settings.secrets_policy,
                         "findings": [f.public() for f in found]})


@app.post("/api/secrets/ignore", dependencies=[Depends(check_csrf)])
async def api_secrets_ignore(request: Request, perms: Perms = Depends(get_perms), db: Session = Depends(get_db)):
    """Segna un risultato come falso positivo (solo per quel documento; "*" = ovunque, solo admin)."""
    data = await request.json()
    rel = str(data.get("path", ""))
    fp = str(data.get("fp", ""))[:64]
    if rel != "*":
        rel = storage.clean_rel(rel)
    allowed = perms.user.is_admin or (rel != "*" and settings.secrets_policy != "block" and perms.can_edit(rel))
    if not allowed or not fp:
        raise Denied("edit", rel)
    if not db.scalar(select(SecretIgnore).where(SecretIgnore.path == rel, SecretIgnore.fp == fp)):
        db.add(SecretIgnore(path=rel, fp=fp, label=str(data.get("label", ""))[:120],
                            masked=str(data.get("masked", ""))[:64], created_by=perms.user.username))
        db.commit()
    _reload_secret_ignores()
    log.info("%s ha segnato come falso positivo %s in %s", perms.user.username, fp, rel)
    return JSONResponse({"ok": True})


@app.post("/api/create", dependencies=[Depends(check_csrf)])
async def api_create(request: Request, perms: Perms = Depends(get_perms)):
    """Creazione rapida: mode = page | folder | tree. Vedi app/creator.py."""
    if not perms.user.can_edit:
        raise Denied("edit")
    data = await request.json()
    mode = str(data.get("mode", "page"))
    cr = creator.Creator(perms)
    try:
        parent = storage.clean_rel(str(data.get("parent", "")))
        if mode == "tree":
            cr.create_tree(parent, str(data.get("text", "")), index=bool(data.get("index")))
            last = parent
        elif mode in ("page", "folder"):
            last = cr.create_path(parent, str(data.get("title", "")), mode, index=bool(data.get("index")))
        else:
            return JSONResponse({"error": "Modalità non valida."}, status_code=400)
    except (creator.CreateError, PathError) as e:
        return JSONResponse({"error": str(e), "items": cr.as_dicts()}, status_code=400)
    items = cr.as_dicts()
    created = [i for i in items if i["created"]]
    final = items[-1] if items else None
    if mode == "page" and final and not final["created"]:
        return JSONResponse({"error": f"Esiste già una pagina «{final['title']}» qui.", "items": items,
                             "url": f"/d/{quote(final['path'])}"}, status_code=409)
    if mode == "page":
        url = f"/edit/{quote(last)}"
    else:
        url = f"/d/{quote(last)}" if last else "/"
    log.info("%s ha creato %s", perms.user.username, [i["path"] for i in created])
    if data.get("flash") and created:
        flash(request, "Creata 1 voce." if len(created) == 1 else f"Creati {len(created)} elementi.")
    return JSONResponse({"items": items, "created": len(created), "url": url})


@app.post("/upload", dependencies=[Depends(check_csrf)])
async def upload(request: Request, folder: str = Form(""), replace: str = Form(""),
                 files: list[UploadFile] = File(...), perms: Perms = Depends(get_perms)):
    folder = storage.clean_rel(folder)
    _require_edit(perms, folder)
    target_dir = storage.abs_path(folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    limit = settings.max_upload_mb * 1024 * 1024
    saved, errors, warnings = [], [], []
    for f in files:
        try:
            name = storage.safe_filename(f.filename or "")
        except PathError:
            errors.append(f"{f.filename}: nome non valido")
            continue
        if name.rsplit(".", 1)[-1].lower() not in storage.ALLOWED_UPLOAD_EXT:
            errors.append(f"{name}: tipo di file non ammesso")
            continue
        dest = target_dir / name
        if dest.exists() and not replace:
            stem, ext = name.rsplit(".", 1)
            i = 1
            while (target_dir / f"{stem} ({i}).{ext}").exists():
                i += 1
            dest = target_dir / f"{stem} ({i}).{ext}"
        elif dest.exists():
            dest_rel = f"{folder}/{dest.name}" if folder else dest.name
            if not perms.can_edit(dest_rel):
                errors.append(f"{name}: non puoi sovrascrivere questo file")
                continue
        size = 0
        with tempfile.NamedTemporaryFile(dir=settings.cache_dir, delete=False, suffix="." + name.rsplit(".", 1)[-1]) as tmp:
            while chunk := await f.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    break
                tmp.write(chunk)
        if size > limit:
            Path(tmp.name).unlink(missing_ok=True)
            errors.append(f"{name}: supera {settings.max_upload_mb} MB")
            continue
        found = await asyncio.to_thread(secretscan.scan_file, Path(tmp.name)) if settings.secrets_scan else []
        if found and settings.secrets_policy == "block":
            Path(tmp.name).unlink(missing_ok=True)
            errors.append(f"{name}: contiene {len(found)} possibili password o credenziali ({found[0].location}). "
                          "Toglile e ricarica il file.")
            continue
        shutil.move(tmp.name, dest)
        dest.chmod(0o644)
        dest_rel = f"{folder}/{dest.name}" if folder else dest.name
        saved.append(dest_rel)
        if found:
            visible = await asyncio.to_thread(secretscan.SCANNER.rescan, dest_rel)
            if visible:
                warnings.append({"path": dest_rel, "count": len(visible)})
                log.warning("%s ha caricato %s con %d possibili password", perms.user.username, dest_rel, len(visible))
    log.info("%s ha caricato %s", perms.user.username, saved)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"saved": saved, "errors": errors, "secrets": warnings})
    if saved:
        flash(request, f"Caricati {len(saved)} file.")
    for w in warnings:
        flash(request, f"Attenzione: «{w['path'].rsplit('/', 1)[-1]}» sembra contenere {w['count']} password o "
                       "credenziali. Aprilo per vedere dove.", "warn")
    for e in errors:
        flash(request, e, "error")
    return RedirectResponse(f"/d/{quote(folder)}" if folder else "/", status_code=303)


@app.post("/mkdir", dependencies=[Depends(check_csrf)])
async def mkdir(request: Request, folder: str = Form(""), name: str = Form(...), perms: Perms = Depends(get_perms)):
    folder = storage.clean_rel(folder)
    _require_edit(perms, folder)
    name = storage.safe_filename(name)
    rel = f"{folder}/{name}" if folder else name
    p = storage.abs_path(rel)
    if p.exists():
        flash(request, f"«{name}» esiste già.", "error")
    else:
        p.mkdir(parents=True)
        flash(request, f"Cartella «{name}» creata.")
    return RedirectResponse(f"/d/{quote(rel)}", status_code=303)


def _move_restrictions(db: Session, old: str, new: str | None) -> None:
    """Sposta (o elimina se new=None) le restrizioni sotto `old`."""
    rs = db.scalars(select(Restriction).options(selectinload(Restriction.entries))).all()
    for r in rs:
        if r.path == old or r.path.startswith(old + "/"):
            if new is not None:
                np_ = new + r.path[len(old):]
                nr = Restriction(path=np_)
                nr.entries = [AclEntry(principal_type=e.principal_type, principal_value=e.principal_value,
                                       level=e.level) for e in r.entries]
                db.delete(r)
                db.flush()
                db.add(nr)
            else:
                db.delete(r)
    db.commit()


@app.post("/delete", dependencies=[Depends(check_csrf)])
async def delete(request: Request, path: str = Form(...), perms: Perms = Depends(get_perms),
                 db: Session = Depends(get_db)):
    rel = storage.clean_rel(path)
    if not rel:
        raise Denied("edit", rel)
    _require_edit(perms, rel)
    p = storage.abs_path(rel)
    if p.is_dir():
        # serve il permesso di modifica su tutto il contenuto
        for sub in p.rglob("*"):
            srel = sub.relative_to(settings.docs_dir.resolve()).as_posix()
            if not perms.can_edit(srel):
                flash(request, "La cartella contiene elementi che non puoi modificare.", "error")
                return RedirectResponse(f"/d/{quote(rel)}", status_code=303)
    storage.remove(rel)
    _move_restrictions(db, rel, None)
    secretscan.SCANNER.forget(rel)
    log.info("%s ha eliminato %s", perms.user.username, rel)
    flash(request, f"«{p.name}» eliminato.")
    parent = storage.parent_of(rel)
    return RedirectResponse(f"/d/{quote(parent)}" if parent else "/", status_code=303)


@app.post("/move", dependencies=[Depends(check_csrf)])
async def move(request: Request, path: str = Form(...), dest_folder: str = Form(""), new_name: str = Form(...),
               perms: Perms = Depends(get_perms), db: Session = Depends(get_db)):
    rel = storage.clean_rel(path)
    dest_folder = storage.clean_rel(dest_folder)
    if not rel:
        raise Denied("edit", rel)
    _require_edit(perms, rel)
    _require_edit(perms, dest_folder)
    name = storage.safe_filename(new_name)
    src = storage.abs_path(rel)
    new_rel = f"{dest_folder}/{name}" if dest_folder else name
    dst = storage.abs_path(new_rel)
    if not src.exists():
        raise NotFound()
    if dst.exists():
        flash(request, "Esiste già un elemento con quel nome nella destinazione.", "error")
        return RedirectResponse(f"/d/{quote(rel)}", status_code=303)
    if src.is_dir() and (new_rel + "/").startswith(rel + "/"):
        flash(request, "Non puoi spostare una cartella dentro se stessa.", "error")
        return RedirectResponse(f"/d/{quote(rel)}", status_code=303)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    _move_restrictions(db, rel, new_rel)
    secretscan.SCANNER.forget(rel)
    flash(request, "Elemento spostato/rinominato.")
    return RedirectResponse(f"/d/{quote(new_rel)}", status_code=303)


def all_folders(node: storage.Node, perms: Perms) -> list[str]:
    out = [node.path] if perms.can_edit(node.path) else []
    for c in node.children:
        if c.is_dir:
            out += all_folders(c, perms)
    return out


templates.env.globals["all_folders"] = all_folders


# ----------------------------------------------------------------- admin
@app.get("/admin", include_in_schema=False)
async def admin_home(_perms: Perms = Depends(get_admin)):
    return RedirectResponse("/admin/permissions", status_code=303)


@app.get("/admin/roles", response_class=HTMLResponse)
async def admin_roles(request: Request, edit: int | None = None, perms: Perms = Depends(get_admin),
                      db: Session = Depends(get_db)):
    roles = db.scalars(select(AppRole).options(selectinload(AppRole.groups)).order_by(AppRole.name)).all()
    groups = db.scalars(select(LocalGroup).order_by(LocalGroup.name)).all()
    editing = next((r for r in roles if r.id == edit), None)
    return render(request, "admin/roles.html", {
        "tree": perms.filter_tree(storage.build_tree()), "roles": roles, "groups": groups,
        "editing": editing, "section": "roles", "admin_env_roles": settings.admin_roles,
    })


@app.post("/admin/roles", dependencies=[Depends(check_csrf)])
async def admin_roles_save(request: Request, perms: Perms = Depends(get_admin), db: Session = Depends(get_db)):
    form = await request.form()
    rid = form.get("id")
    name = str(form.get("name", "")).strip()
    if not name:
        flash(request, "Il nome è obbligatorio.", "error")
        return RedirectResponse("/admin/roles", status_code=303)
    role = db.get(AppRole, int(rid)) if rid else AppRole()
    clash = db.scalar(select(AppRole).where(AppRole.name == name))
    if clash and clash.id != role.id:
        flash(request, f"Esiste già un ruolo «{name}».", "error")
        return RedirectResponse("/admin/roles", status_code=303)
    old_name = role.name
    role.name = name
    role.description = str(form.get("description", "")).strip()
    role.keycloak_roles = sorted({x.strip() for x in str(form.get("keycloak_roles", "")).replace("\n", ",").split(",") if x.strip()})
    lvl = str(form.get("global_level", "none"))
    role.global_level = lvl if lvl in LEVELS else "none"
    gids = {int(g) for g in form.getlist("groups")}
    role.groups = db.scalars(select(LocalGroup).where(LocalGroup.id.in_(gids))).all() if gids else []
    db.add(role)
    if old_name and old_name != name:  # mantieni le ACL che citano il ruolo
        for e in db.scalars(select(AclEntry).where(AclEntry.principal_type == "app_role",
                                                   AclEntry.principal_value == old_name)):
            e.principal_value = name
    db.commit()
    flash(request, f"Ruolo «{name}» salvato.")
    return RedirectResponse("/admin/roles", status_code=303)


@app.post("/admin/roles/{rid}/delete", dependencies=[Depends(check_csrf)])
async def admin_roles_delete(request: Request, rid: int, perms: Perms = Depends(get_admin),
                             db: Session = Depends(get_db)):
    role = db.get(AppRole, rid)
    if role:
        for e in db.scalars(select(AclEntry).where(AclEntry.principal_type == "app_role",
                                                   AclEntry.principal_value == role.name)):
            db.delete(e)
        db.delete(role)
        db.commit()
        flash(request, f"Ruolo «{role.name}» eliminato (e rimosso dai permessi).")
    return RedirectResponse("/admin/roles", status_code=303)


@app.get("/admin/groups", response_class=HTMLResponse)
async def admin_groups(request: Request, edit: int | None = None, perms: Perms = Depends(get_admin),
                       db: Session = Depends(get_db)):
    groups = db.scalars(select(LocalGroup).options(selectinload(LocalGroup.members), selectinload(LocalGroup.roles))
                        .order_by(LocalGroup.name)).all()
    editing = next((g for g in groups if g.id == edit), None)
    return render(request, "admin/groups.html", {
        "tree": perms.filter_tree(storage.build_tree()), "groups": groups, "editing": editing, "section": "groups",
    })


@app.post("/admin/groups", dependencies=[Depends(check_csrf)])
async def admin_groups_save(request: Request, perms: Perms = Depends(get_admin), db: Session = Depends(get_db)):
    form = await request.form()
    gid = form.get("id")
    name = str(form.get("name", "")).strip()
    if not name:
        flash(request, "Il nome è obbligatorio.", "error")
        return RedirectResponse("/admin/groups", status_code=303)
    group = db.get(LocalGroup, int(gid)) if gid else LocalGroup()
    clash = db.scalar(select(LocalGroup).where(LocalGroup.name == name))
    if clash and clash.id != group.id:
        flash(request, f"Esiste già un gruppo «{name}».", "error")
        return RedirectResponse("/admin/groups", status_code=303)
    old_name = group.name
    group.name = name
    group.description = str(form.get("description", "")).strip()
    idents = []
    for line in str(form.get("members", "")).replace(",", "\n").splitlines():
        v = line.strip().lower()
        if v and v not in idents:
            idents.append(v)
    group.members = [GroupMember(identifier=i) for i in idents]
    db.add(group)
    if old_name and old_name != name:
        for e in db.scalars(select(AclEntry).where(AclEntry.principal_type == "group",
                                                   AclEntry.principal_value == old_name)):
            e.principal_value = name
    db.commit()
    flash(request, f"Gruppo «{name}» salvato ({len(idents)} membri).")
    return RedirectResponse("/admin/groups", status_code=303)


@app.post("/admin/groups/{gid}/delete", dependencies=[Depends(check_csrf)])
async def admin_groups_delete(request: Request, gid: int, perms: Perms = Depends(get_admin),
                              db: Session = Depends(get_db)):
    g = db.get(LocalGroup, gid)
    if g:
        for e in db.scalars(select(AclEntry).where(AclEntry.principal_type == "group", AclEntry.principal_value == g.name)):
            db.delete(e)
        db.delete(g)
        db.commit()
        flash(request, f"Gruppo «{g.name}» eliminato.")
    return RedirectResponse("/admin/groups", status_code=303)


@app.get("/admin/permissions", response_class=HTMLResponse)
async def admin_permissions(request: Request, path: str = "", perms: Perms = Depends(get_admin),
                            db: Session = Depends(get_db)):
    rel = storage.clean_rel(path)
    full = storage.build_tree()
    perms.filter_tree(full)  # imposta i livelli (admin vede tutto)
    restriction = db.get(Restriction, rel)
    governing = perms.governing(rel)
    gov_entries = perms.restrictions.get(governing, []) if governing is not None else []
    roles = db.scalars(select(AppRole).order_by(AppRole.name)).all()
    groups = db.scalars(select(LocalGroup).order_by(LocalGroup.name)).all()
    p = storage.abs_path(rel)
    return render(request, "admin/permissions.html", {
        "tree": full, "full": full, "sel": rel, "restriction": restriction, "governing": governing,
        "gov_entries": gov_entries, "roles": roles, "groups": groups, "section": "permissions",
        "restricted_paths": set(perms.restrictions), "exists": p.exists(), "is_dir": p.is_dir(),
        "sel_kind": "folder" if p.is_dir() else storage.kind_of(p.name),
        "sel_title": ((n.title if (n := find_node(full, rel)) else storage.pretty(p.name))
                      if rel else "Tutta la documentazione"),
    })


@app.post("/admin/permissions", dependencies=[Depends(check_csrf)])
async def admin_permissions_save(request: Request, perms: Perms = Depends(get_admin), db: Session = Depends(get_db)):
    form = await request.form()
    rel = storage.clean_rel(str(form.get("path", "")))
    action = form.get("action")
    r = db.get(Restriction, rel)
    if action == "restrict" and r is None:
        r = Restriction(path=rel)
        if form.get("copy_from_parent"):
            gov = perms.governing(rel)
            for e in perms.restrictions.get(gov, []) if gov is not None else []:
                r.entries.append(AclEntry(principal_type=e.principal_type, principal_value=e.principal_value, level=e.level))
        db.add(r)
        flash(request, "Accesso ristretto: ora solo le voci elencate possono accedere.")
    elif action == "unrestrict" and r is not None:
        db.delete(r)
        flash(request, "Restrizione rimossa: valgono di nuovo i permessi ereditati.")
    elif action == "add" and r is not None:
        ptype = str(form.get("principal_type", ""))
        pval = str(form.get(f"value_{ptype}", "") or form.get("principal_value", "")).strip()
        level = str(form.get("level", "view"))
        if ptype in PRINCIPAL_TYPES and pval and level in ("view", "edit"):
            existing = next((e for e in r.entries if e.principal_type == ptype
                             and e.principal_value.lower() == pval.lower()), None)
            if existing:
                existing.level = level
            else:
                r.entries.append(AclEntry(principal_type=ptype, principal_value=pval, level=level))
            flash(request, "Permesso aggiunto.")
        else:
            flash(request, "Compila tutti i campi.", "error")
    elif action == "remove" and r is not None:
        eid = int(form.get("entry_id", 0))
        for e in list(r.entries):
            if e.id == eid:
                r.entries.remove(e)
        flash(request, "Permesso rimosso.")
    elif action == "level" and r is not None:
        eid = int(form.get("entry_id", 0))
        for e in r.entries:
            if e.id == eid and form.get("level") in ("view", "edit"):
                e.level = str(form.get("level"))
    db.commit()
    return RedirectResponse(f"/admin/permissions?path={quote(rel)}", status_code=303)


@app.get("/admin/secrets", response_class=HTMLResponse)
async def admin_secrets(request: Request, perms: Perms = Depends(get_admin), db: Session = Depends(get_db)):
    secretscan.SCANNER.refresh(wait=False)
    found = secretscan.SCANNER.all()
    ignores = db.scalars(select(SecretIgnore).order_by(SecretIgnore.created_at.desc())).all()
    return render(request, "admin/secrets.html", {
        "tree": perms.filter_tree(storage.build_tree()), "section": "secrets", "found": found,
        "ignores": ignores, "scanned": len(secretscan.SCANNER.docs), "enabled": settings.secrets_scan,
        "last_scan": fmt_time(secretscan.SCANNER.last_full_scan) if secretscan.SCANNER.last_full_scan else None,
        "kinds": {rel: storage.kind_of(rel) for rel in found},
    })


@app.post("/admin/secrets", dependencies=[Depends(check_csrf)])
async def admin_secrets_action(request: Request, perms: Perms = Depends(get_admin), db: Session = Depends(get_db)):
    form = await request.form()
    action = form.get("action")
    if action == "rescan":
        secretscan.SCANNER.docs.clear()
        await asyncio.to_thread(secretscan.SCANNER.refresh, True)
        flash(request, "Controllo completato su tutti i documenti.")
    elif action == "unignore":
        row = db.get(SecretIgnore, int(form.get("id", 0)))
        if row:
            db.delete(row)
            db.commit()
            _reload_secret_ignores()
            flash(request, "Il risultato tornerà a essere segnalato.")
    return RedirectResponse("/admin/secrets", status_code=303)


@app.get("/admin/branding", response_class=HTMLResponse)
async def admin_branding(request: Request, perms: Perms = Depends(get_admin)):
    files = {k: logo_file(k) for k in LOGO_KINDS}
    return render(request, "admin/branding.html", {
        "tree": perms.filter_tree(storage.build_tree()), "section": "branding",
        "files": {k: (v.name if v else None) for k, v in files.items()},
    })


@app.post("/admin/branding", dependencies=[Depends(check_csrf)])
async def admin_branding_save(request: Request, which: str = Form(...), action: str = Form("upload"),
                              file: UploadFile | None = File(None), perms: Perms = Depends(get_admin)):
    if which not in LOGO_KINDS:
        raise NotFound()
    current = logo_file(which)
    readonly_msg = "I loghi sono gestiti dal deploy (cartella in sola lettura): modificali lì."
    if action == "delete":
        try:
            if current:
                current.unlink()
            flash(request, "Logo rimosso.")
        except OSError:
            flash(request, readonly_msg, "error")
        return RedirectResponse("/admin/branding", status_code=303)
    if not file or not file.filename:
        flash(request, "Seleziona un file.", "error")
        return RedirectResponse("/admin/branding", status_code=303)
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in LOGO_EXTS:
        flash(request, "Formato non supportato: usa SVG, PNG, WEBP o JPG.", "error")
        return RedirectResponse("/admin/branding", status_code=303)
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        flash(request, "Il logo deve pesare meno di 5 MB.", "error")
        return RedirectResponse("/admin/branding", status_code=303)
    ext = "jpg" if ext == "jpeg" else ext
    try:
        if current:
            current.unlink()
        (settings.branding_dir / f"{LOGO_KINDS[which]}.{ext}").write_bytes(data)
        flash(request, "Logo aggiornato.")
    except OSError:
        flash(request, readonly_msg, "error")
    return RedirectResponse("/admin/branding", status_code=303)
