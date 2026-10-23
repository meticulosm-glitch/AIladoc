"""Accesso con utenti locali (senza Keycloak)."""
import re

import pytest

from app import auth
from app.config import _local_users, settings


@pytest.fixture()
def local(monkeypatch, tmp_path):
    pw = tmp_path / "pw"
    pw.mkdir()
    (pw / "admin").write_text("S3greta-lunga\n")
    (pw / "mario").write_text("altra")
    monkeypatch.setattr(settings, "dev_auth", False)
    monkeypatch.setattr(settings, "login_mode", "form")
    monkeypatch.setattr(settings, "local_users", {"admin": ["ailadoc-admin"], "mario": ["ailadoc-viewer"],
                                                  "senzapw": []})
    monkeypatch.setattr(settings, "local_users_dir", pw)

    async def no_keycloak(*a, **kw):
        raise AssertionError("Keycloak non deve essere chiamato")
    monkeypatch.setattr(auth, "password_login", no_keycloak)
    from app import main
    main._login_failures.clear()
    return pw


def _post(client, username, password, url="/login", nxt="/"):
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get(url).text).group(1)
    return client.post("/login", data={"username": username, "password": password, "next": nxt, "csrf": csrf},
                       follow_redirects=False)


def test_parse_local_users():
    assert _local_users("") == {}
    assert _local_users("admin, Mario") == {"admin": [], "mario": []}
    assert _local_users('{"Admin": ["ailadoc-admin", "x"], "v": "ailadoc-viewer"}') == {
        "admin": ["ailadoc-admin", "x"], "v": ["ailadoc-viewer"]}
    assert _local_users('{"../etc": [], "ok": []}') == {"ok": []}
    assert _local_users("{non json") == {}


def test_admin_locale(client, local):
    r = _post(client, "Admin", "S3greta-lunga", nxt="/admin/roles")
    assert r.status_code == 303 and r.headers["location"] == "/admin/roles"
    assert client.get("/admin/roles").status_code == 200  # ruolo ailadoc-admin => amministratore
    loc = client.get("/logout", follow_redirects=False).headers["location"]
    assert loc == "/login"  # niente logout su Keycloak


def test_lettore_locale(client, local):
    assert _post(client, "mario", "altra").status_code == 303
    assert client.get("/").status_code == 200
    assert client.get("/admin/roles").status_code == 403


def test_password_sbagliata_o_mancante(client, local):
    r = _post(client, "admin", "S3greta")
    assert r.status_code == 401 and "non corretti" in r.text
    assert _post(client, "senzapw", "").status_code == 400  # password vuota: campo obbligatorio
    assert _post(client, "senzapw", "qualsiasi").status_code == 401
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/login")


def test_password_cambiata_vale_subito(client, local):
    (local / "admin").write_text("nuova")
    assert _post(client, "admin", "S3greta-lunga").status_code == 401
    assert _post(client, "admin", "nuova").status_code == 303


def test_troppi_tentativi_locali(client, local, monkeypatch):
    monkeypatch.setattr(settings, "login_max_attempts", 2)
    assert _post(client, "admin", "no").status_code == 401
    assert _post(client, "admin", "no").status_code == 401
    assert _post(client, "admin", "S3greta-lunga").status_code == 429


def test_modalita_redirect(client, local, monkeypatch):
    monkeypatch.setattr(settings, "login_mode", "redirect")
    loc = client.get("/login", follow_redirects=False).headers["location"]
    assert loc.startswith("http://kc.public/")  # /login resta il Single Sign-On
    page = client.get("/login/local")
    assert page.status_code == 200 and "credenziali locali" in page.text and "/login/sso" in page.text
    r = _post(client, "mrossi", "x", url="/login/local")  # utente non locale: niente Keycloak
    assert r.status_code == 401
    assert _post(client, "admin", "S3greta-lunga", url="/login/local").status_code == 303
    assert client.get("/logout", follow_redirects=False).headers["location"] == "/login/local"


def test_senza_utenti_locali(client, local, monkeypatch):
    monkeypatch.setattr(settings, "local_users", {})
    monkeypatch.setattr(settings, "login_mode", "redirect")
    assert client.get("/login/local", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"username": "admin", "password": "x"}).status_code == 404
