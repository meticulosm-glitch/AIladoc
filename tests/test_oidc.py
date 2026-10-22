"""Login contro un Keycloak simulato (chiavi RSA vere, token firmati): pagina dell'app e redirect OIDC."""
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey

from app import auth
from app.config import settings

KEY = RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"})
ISS = "http://kc.public/realms/ailadoc"


def _token(claims):
    now = int(time.time())
    base = {"iss": ISS, "iat": now, "exp": now + 300}
    return jwt.encode({"alg": "RS256", "kid": "k1"}, {**base, **claims}, KEY)


def _at():
    return _token({"aud": "account", "sub": "u1", "realm_access": {"roles": ["ailadoc-viewer", "offline_access"]},
                   "resource_access": {"ailadoc": {"roles": ["redattore"]}, "crm": {"roles": ["user"]}},
                   "groups": ["/Azienda/Vendite"]})


@pytest.fixture()
def fake_keycloak(monkeypatch):
    state = {"nonce": None, "token_calls": 0, "password_reply": None, "form": None}

    def handler(request: httpx.Request):
        assert request.url.host == "kc.internal", "il back-channel deve usare l'URL interno"
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [KEY.as_dict(private=False)]})
        if request.url.path.endswith("/token"):
            state["token_calls"] += 1
            form = parse_qs(request.content.decode())
            state["form"] = form
            if form["grant_type"] == ["password"]:
                if state["password_reply"]:
                    return httpx.Response(state["password_reply"][0], json=state["password_reply"][1])
                if form["username"] != ["mrossi"] or form["password"] != ["giusta"]:
                    return httpx.Response(401, json={"error": "invalid_grant",
                                                     "error_description": "Invalid user credentials"})
                idt = _token({"aud": "ailadoc", "sub": "u1", "preferred_username": "mrossi",
                              "email": "m.rossi@example.com", "name": "Mario Rossi"})
                return httpx.Response(200, json={"id_token": idt, "access_token": _at()})
            assert form["code"] == ["abc"] and form["code_verifier"][0]
            idt = _token({"aud": "ailadoc", "sub": "u1", "nonce": state["nonce"], "preferred_username": "mrossi",
                          "email": "m.rossi@example.com", "name": "Mario Rossi"})
            at = _token({"aud": "account", "sub": "u1", "realm_access": {"roles": ["ailadoc-viewer", "offline_access"]},
                         "resource_access": {"ailadoc": {"roles": ["redattore"]}, "crm": {"roles": ["user"]}},
                         "groups": ["/Azienda/Vendite"]})
            return httpx.Response(200, json={"id_token": idt, "access_token": at})
        return httpx.Response(404)

    real = httpx.AsyncClient
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    auth._jwks_cache.update(keys=None, at=0)
    monkeypatch.setattr(settings, "dev_auth", False)
    monkeypatch.setattr(settings, "login_mode", "form")
    from app import main
    main._login_failures.clear()
    return state


def test_login_oidc_completo(client, fake_keycloak):
    r = client.get("/login/sso?next=/d/01-Guida", follow_redirects=False)
    loc = urlparse(r.headers["location"])
    assert loc.netloc == "kc.public" and loc.path == "/realms/ailadoc/protocol/openid-connect/auth"
    q = parse_qs(loc.query)
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"] == ["http://testserver/auth/callback"]
    fake_keycloak["nonce"] = q["nonce"][0]

    r = client.get(f"/auth/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/d/01-Guida"
    me = client.get("/me").text
    for role in ("ailadoc-viewer", "redattore", "crm:user", "Vendite", "/Azienda/Vendite"):
        assert role in me
    assert "Mario Rossi" in me
    assert client.get("/d/01-Guida/01-primi-passi.md").status_code == 200

    r = client.get("/logout", follow_redirects=False)
    assert r.headers["location"].startswith("http://kc.public/realms/ailadoc/protocol/openid-connect/logout")


def test_state_errato_rifiutato(client, fake_keycloak):
    client.get("/login/sso", follow_redirects=False)
    r = client.get("/auth/callback?code=abc&state=sbagliato")
    assert r.status_code == 400 and fake_keycloak["token_calls"] == 0


def test_nonce_errato_rifiutato(client, fake_keycloak):
    r = client.get("/login/sso", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    fake_keycloak["nonce"] = "altro"
    r = client.get(f"/auth/callback?code=abc&state={q['state'][0]}")
    assert r.status_code == 400
    assert client.get("/", follow_redirects=False).status_code == 303  # non loggato


def test_extract_roles():
    roles = auth.extract_roles({
        "realm_access": {"roles": ["a"]},
        "resource_access": {"ailadoc": {"roles": ["b"]}, "x": {"roles": ["c"]}},
        "groups": ["/g/h"], "roles": "single",
    })
    assert {"a", "b", "ailadoc:b", "x:c", "/g/h", "h", "single"} <= roles and "c" not in roles


# --------------------------------------------------- pagina di login dell'app
def _csrf(client, url="/login"):
    r = client.get(url)
    assert r.status_code == 200
    return re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)


def _post_login(client, username="mrossi", password="giusta", nxt="/", **extra):
    data = {"username": username, "password": password, "next": nxt, "csrf": _csrf(client), **extra}
    return client.post("/login", data=data, follow_redirects=False)


def test_login_mostra_la_pagina_dell_app(client, fake_keycloak):
    r = client.get("/login?next=/d/01-Guida", follow_redirects=False)
    assert r.status_code == 200 and "kc.public" not in r.text
    assert 'action="/login"' in r.text and 'name="password"' in r.text
    assert 'name="next" value="/d/01-Guida"' in r.text
    assert fake_keycloak["token_calls"] == 0


def test_login_con_credenziali(client, fake_keycloak):
    r = _post_login(client, nxt="/d/01-Guida")
    assert r.status_code == 303 and r.headers["location"] == "/d/01-Guida"
    form = fake_keycloak["form"]
    assert form["grant_type"] == ["password"] and form["client_id"] == ["ailadoc"]
    assert "openid" in form["scope"][0].split() and "totp" not in form
    me = client.get("/me").text
    for role in ("ailadoc-viewer", "redattore", "crm:user", "Vendite"):
        assert role in me
    assert "Mario Rossi" in me
    assert client.get("/login", follow_redirects=False).status_code == 303  # già dentro
    loc = client.get("/logout", follow_redirects=False).headers["location"]
    assert loc.startswith("http://kc.public/realms/ailadoc/protocol/openid-connect/logout") and "id_token_hint=" in loc


def test_password_sbagliata(client, fake_keycloak):
    r = _post_login(client, password="sbagliata")
    assert r.status_code == 401
    assert "non corretti" in r.text and 'value="mrossi"' in r.text and "sbagliata" not in r.text
    assert client.get("/", follow_redirects=False).headers["location"].startswith("/login")


def test_csrf_obbligatorio(client, fake_keycloak):
    client.get("/login")
    r = client.post("/login", data={"username": "mrossi", "password": "giusta", "csrf": "x"}, follow_redirects=False)
    assert r.status_code == 400 and fake_keycloak["token_calls"] == 0


def test_troppi_tentativi(client, fake_keycloak, monkeypatch):
    monkeypatch.setattr(settings, "login_max_attempts", 2)
    assert _post_login(client, password="no").status_code == 401
    assert _post_login(client, password="no").status_code == 401
    r = _post_login(client)  # anche con la password giusta: prima bisogna aspettare
    assert r.status_code == 429 and fake_keycloak["token_calls"] == 2


def test_account_da_completare_va_su_keycloak(client, fake_keycloak):
    fake_keycloak["password_reply"] = (400, {"error": "invalid_grant", "error_description": "Account is not fully set up"})
    r = _post_login(client, nxt="/d/01-Guida")
    assert r.status_code == 400 and "passaggio in più" in r.text
    assert "/login/sso?next=/d/01-Guida&amp;login_hint=mrossi" in r.text
    loc = client.get("/login/sso?next=/d/01-Guida&login_hint=mrossi", follow_redirects=False).headers["location"]
    assert parse_qs(urlparse(loc).query)["login_hint"] == ["mrossi"]


def test_direct_grant_non_abilitato(client, fake_keycloak):
    fake_keycloak["password_reply"] = (400, {"error": "unauthorized_client",
                                             "error_description": "Client not allowed for direct access grants"})
    r = _post_login(client)
    assert r.status_code == 400 and "Single Sign-On" in r.text and "/login/sso" in r.text


def test_account_bloccato_o_disabilitato(client, fake_keycloak):
    fake_keycloak["password_reply"] = (400, {"error": "invalid_grant", "error_description": "Account temporarily disabled"})
    assert _post_login(client).status_code == 423
    fake_keycloak["password_reply"] = (400, {"error": "invalid_grant", "error_description": "Account disabled"})
    assert "disabilitato" in _post_login(client).text


def test_next_esterno_ignorato(client, fake_keycloak):
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example"):
        client.get("/logout")
        assert _post_login(client, nxt=bad).headers["location"] == "/"


def test_otp_inoltrato(client, fake_keycloak, monkeypatch):
    monkeypatch.setattr(settings, "login_otp", True)
    assert 'name="otp"' in client.get("/login").text
    _post_login(client, otp="123 456")
    assert fake_keycloak["form"]["totp"] == ["123456"]


def test_modalita_redirect(client, fake_keycloak, monkeypatch):
    monkeypatch.setattr(settings, "login_mode", "redirect")
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("http://kc.public/")
    assert client.post("/login", data={"username": "a", "password": "b"}).status_code == 404
