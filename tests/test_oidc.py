"""Flusso OIDC completo contro un Keycloak simulato (chiavi RSA vere, token firmati)."""
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


@pytest.fixture()
def fake_keycloak(monkeypatch):
    state = {"nonce": None, "token_calls": 0}

    def handler(request: httpx.Request):
        assert request.url.host == "kc.internal", "il back-channel deve usare l'URL interno"
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [KEY.as_dict(private=False)]})
        if request.url.path.endswith("/token"):
            state["token_calls"] += 1
            form = parse_qs(request.content.decode())
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
    return state


def test_login_oidc_completo(client, fake_keycloak):
    r = client.get("/login?next=/d/01-Guida", follow_redirects=False)
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
    client.get("/login", follow_redirects=False)
    r = client.get("/auth/callback?code=abc&state=sbagliato")
    assert r.status_code == 400 and fake_keycloak["token_calls"] == 0


def test_nonce_errato_rifiutato(client, fake_keycloak):
    r = client.get("/login", follow_redirects=False)
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
