"""Utenti locali: accesso con nome utente e password senza passare da Keycloak.

Gli utenti e i loro ruoli arrivano da LOCAL_USERS (vedi config); la password di ciascuno è
il contenuto del file LOCAL_USERS_DIR/<nome> (nel chart Helm: il Secret generato dal Job,
montato come volume, quindi una password cambiata vale subito, senza riavviare).
"""
from __future__ import annotations

import hmac
import logging
import time

from .auth import LoginError
from .config import settings

log = logging.getLogger("ailadoc.localusers")
_BAD = "Nome utente o password non corretti."


def is_local(username: str) -> bool:
    return username.strip().lower() in settings.local_users


def _password(name: str) -> str:
    try:
        return (settings.local_users_dir / name).read_text(encoding="utf-8").rstrip("\r\n")
    except OSError:
        return ""


def has_password(name: str) -> bool:
    return bool(_password(name))


def authenticate(username: str, password: str) -> dict:
    """Utente di sessione se nome e password corrispondono, altrimenti LoginError("credentials")."""
    name = username.strip().lower()
    if name not in settings.local_users:
        raise LoginError("credentials", _BAD)
    expected = _password(name)
    if not expected:
        log.warning("Utente locale %r senza password in %s: accesso rifiutato", name, settings.local_users_dir)
        raise LoginError("credentials", _BAD)
    if not hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8")):
        raise LoginError("credentials", _BAD)
    return {
        "sub": f"local:{name}",
        "username": name,
        "email": "",
        "name": name,
        "roles": list(settings.local_users[name]),
        "local": True,
        "login_at": int(time.time()),
    }
