"""Login OIDC con Keycloak (Authorization Code + PKCE) ed estrazione dei ruoli."""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import ssl
import time
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from .config import settings

log = logging.getLogger("ailadoc.auth")
ALGS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]
_jwks_cache: dict = {"keys": None, "at": 0.0}


class AuthError(Exception):
    pass


def _verify():
    """Verifica TLS verso Keycloak: CA interna (OIDC_CA_FILE), default di sistema o disattivata."""
    if not settings.verify_tls:
        return False
    if settings.ca_file:
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cafile=settings.ca_file)
        return ctx
    return True


def _endpoint(name: str, public: bool = False) -> str:
    base = settings.issuer if public else settings.internal_issuer_base
    return f"{base}/protocol/openid-connect/{name}"


def build_login_redirect(session: dict, next_url: str = "/") -> str:
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "next": next_url}
    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": settings.oidc_scopes,
        "redirect_uri": f"{settings.base_url}/auth/callback",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{_endpoint('auth', public=True)}?{urlencode(params)}"


def build_logout_redirect(id_token: str | None = None) -> str:
    params = {"client_id": settings.oidc_client_id, "post_logout_redirect_uri": f"{settings.base_url}/"}
    if id_token:  # evita la pagina di conferma di Keycloak e chiude davvero la sessione SSO
        params["id_token_hint"] = id_token
    return f"{_endpoint('logout', public=True)}?{urlencode(params)}"


async def _jwks(force: bool = False):
    if force or not _jwks_cache["keys"] or time.time() - _jwks_cache["at"] > 3600:
        async with httpx.AsyncClient(verify=_verify(), timeout=10) as c:
            r = await c.get(_endpoint("certs"))
            r.raise_for_status()
            _jwks_cache["keys"] = KeySet.import_key_set(
                {"keys": [k for k in r.json().get("keys", []) if k.get("use", "sig") == "sig"]})
            _jwks_cache["at"] = time.time()
    return _jwks_cache["keys"]


async def _decode(token: str, options: dict) -> dict:
    for force in (False, True):
        keys = await _jwks(force)
        try:
            tok = jwt.decode(token, keys, algorithms=ALGS)
            jwt.JWTClaimsRegistry(leeway=60, **options).validate(tok.claims)
            return dict(tok.claims)
        except (JoseError, ValueError) as e:
            if force:
                raise AuthError(f"Token non valido: {e}") from e
    raise AuthError("Token non valido")


async def handle_callback(session: dict, code: str, state: str) -> tuple[dict, str, str]:
    pending = session.pop("oidc", None)
    if not pending or not secrets.compare_digest(pending["state"], state or ""):
        raise AuthError("Stato OIDC non valido o scaduto: riprova ad accedere.")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"{settings.base_url}/auth/callback",
        "client_id": settings.oidc_client_id,
        "code_verifier": pending["verifier"],
    }
    if settings.oidc_client_secret:
        data["client_secret"] = settings.oidc_client_secret
    async with httpx.AsyncClient(verify=_verify(), timeout=15) as c:
        r = await c.post(_endpoint("token"), data=data)
    if r.status_code != 200:
        log.warning("Token endpoint %s: %s", r.status_code, r.text[:500])
        raise AuthError("Keycloak ha rifiutato lo scambio del codice di autorizzazione.")
    tokens = r.json()

    id_claims = await _decode(tokens["id_token"], {
        "iss": {"essential": True, "value": settings.issuer},
        "aud": {"essential": True, "value": settings.oidc_client_id},
        "nonce": {"essential": True, "value": pending["nonce"]},
        "exp": {"essential": True},
    })
    at_claims: dict = {}
    if tokens.get("access_token"):
        try:
            at_claims = await _decode(tokens["access_token"], {"iss": {"essential": True, "value": settings.issuer}})
        except AuthError as e:  # access token opaco o non firmato come atteso
            log.info("Access token non decodificabile, uso solo l'ID token: %s", e)

    merged = {**at_claims, **id_claims}
    roles = sorted(extract_roles(at_claims) | extract_roles(id_claims))
    user = {
        "sub": id_claims.get("sub"),
        "username": merged.get("preferred_username") or merged.get("sub"),
        "email": merged.get("email", ""),
        "name": merged.get("name") or " ".join(
            x for x in (merged.get("given_name"), merged.get("family_name")) if x
        ),
        "roles": roles[:300],
        "login_at": int(time.time()),
    }
    return user, pending.get("next") or "/", tokens["id_token"]


def _dig(claims: dict, dotted: str):
    cur = claims
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def extract_roles(claims: dict) -> set[str]:
    """Ruoli realm, ruoli client (anche come 'client:ruolo') e claim extra (es. groups)."""
    out: set[str] = set()
    for r in (claims.get("realm_access") or {}).get("roles", []) or []:
        out.add(str(r))
    for client, info in (claims.get("resource_access") or {}).items():
        for r in (info or {}).get("roles", []) or []:
            out.add(f"{client}:{r}")
            if client == settings.oidc_client_id:
                out.add(str(r))
    for claim in settings.roles_extra_claims:
        val = _dig(claims, claim)
        if isinstance(val, str):
            val = [val]
        if isinstance(val, list):
            for v in val:
                v = str(v)
                out.add(v)
                if v.startswith("/"):  # gruppi Keycloak con percorso completo
                    out.add(v.rsplit("/", 1)[-1])
    return {r for r in out if r}
