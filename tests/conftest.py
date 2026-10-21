import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DATA = Path(tempfile.mkdtemp(prefix="ailadoc-test-"))
os.environ.update({
    "DATA_DIR": str(_DATA),
    "AUTH_DEV_MODE": "true",
    "SECRET_KEY": "test-secret",
    "BASE_URL": "http://testserver",
    "KEYCLOAK_PUBLIC_URL": "http://kc.public",
    "KEYCLOAK_INTERNAL_URL": "http://kc.internal",
    "KEYCLOAK_REALM": "ailadoc",
    "OIDC_CLIENT_ID": "ailadoc",
    "OFFICE_PREVIEW": "false",
    "ASSISTANT_LLM": "none",
    "ASSISTANT_RESCAN_SECONDS": "0",
    "ASSISTANT_RATE_PER_MINUTE": "1000",
    "SECRETS_RESCAN_SECONDS": "0",
})

from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbm  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def data_dir():
    docs = _DATA / "docs"
    if docs.exists():
        shutil.rmtree(docs)
    shutil.copytree(ROOT / "tests" / "fixtures" / "docs", docs)
    db = _DATA / "ailadoc.db"
    if db.exists():
        db.unlink()
    from app import secretscan  # stato del controllo password pulito per ogni test
    secretscan.SCANNER.docs.clear()
    secretscan.SCANNER.ignored = set()
    (_DATA / "cache" / "secrets.json").unlink(missing_ok=True)
    yield _DATA


@pytest.fixture()
def client(data_dir):
    with TestClient(app) as c:
        yield c


def login(c: TestClient, username: str, roles: str = ""):
    c.get("/logout")
    r = c.post("/dev-login", data={"username": username, "roles": roles, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303
    return c


def csrf(c: TestClient) -> str:
    r = c.get("/me")
    import re
    m = re.search(r'AILADOC = \{csrf: "([^"]+)"', r.text)
    assert m, "csrf non trovato"
    return m.group(1)
