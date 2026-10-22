import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from app import assistant, metrics
from app.config import settings
from conftest import csrf, login


def sample(name: str, **labels) -> float:
    """Valore attuale di una serie (0 se non esiste ancora)."""
    v = metrics.REGISTRY.get_sample_value(name, labels)
    return v or 0.0


def scrape(client) -> dict:
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    return {f.name: f for f in text_string_to_metric_families(r.text)}


def test_endpoint_pubblico_in_formato_prometheus(client):
    fams = scrape(client)  # nessun login richiesto
    for name in ("ailadoc_http_requests", "ailadoc_http_request_duration_seconds", "ailadoc_http_requests_in_progress",
                 "ailadoc_assistant_index_documents", "ailadoc_secret_findings", "ailadoc_app_info",
                 "process_cpu_seconds", "python_info"):
        assert name in fams, name
    info = next(s for s in fams["ailadoc_app_info"].samples)
    assert info.labels["login_mode"] == "dev" and info.labels["llm_provider"] == "none"


def test_route_come_modello_non_percorso_reale(client):
    login(client, "viewer", "ailadoc-viewer")
    before = sample("ailadoc_http_requests_total", method="GET", route="/d/{rel:path}", status="200")
    count_before = sample("ailadoc_http_request_duration_seconds_count", method="GET", route="/d/{rel:path}")
    assert client.get("/d/01-Guida/01-primi-passi.md").status_code == 200
    assert sample("ailadoc_http_requests_total", method="GET", route="/d/{rel:path}", status="200") == before + 1
    assert sample("ailadoc_http_request_duration_seconds_count", method="GET",
                  route="/d/{rel:path}") == count_before + 1
    text = client.get("/metrics").text
    assert "primi-passi" not in text  # nessun nome di documento nelle etichette


def test_percorsi_sconosciuti_e_statici(client):
    before = sample("ailadoc_http_requests_total", method="GET", route="<unmatched>", status="404")
    client.get("/non-esiste/123")
    client.get("/non-esiste/456")
    assert sample("ailadoc_http_requests_total", method="GET", route="<unmatched>", status="404") == before + 2
    st = sample("ailadoc_http_requests_total", method="GET", route="/static", status="200")
    assert client.get("/static/js/app.js").status_code == 200
    assert sample("ailadoc_http_requests_total", method="GET", route="/static", status="200") == st + 1


def test_token_bearer(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_token", "s3greto")
    r = client.get("/metrics")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    assert client.get("/metrics", headers={"Authorization": "Bearer sbagliato"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Basic czNncmV0bw=="}).status_code == 401
    r = client.get("/metrics", headers={"Authorization": "Bearer s3greto"})
    assert r.status_code == 200 and "ailadoc_http_requests_total" in r.text


def test_disattivabile(client, monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", False)
    assert client.get("/metrics").status_code == 404


def test_tempi_assistente_e_login(client):
    dev = sample("ailadoc_logins_total", method="dev", result="success")
    login(client, "viewer", "ailadoc-viewer")
    assert sample("ailadoc_logins_total", method="dev", result="success") == dev + 1

    token = csrf(client)
    n = sample("ailadoc_assistant_answer_duration_seconds_count", mode="search")
    empty = sample("ailadoc_assistant_no_results_total")
    r = client.post("/api/assistant", json={"question": "ferie"}, headers={"x-csrf-token": token})
    assert r.status_code == 200 and r.json()["mode"] == "search"
    client.post("/api/assistant", json={"question": "zxqwkj inesistente"}, headers={"x-csrf-token": token})
    assert sample("ailadoc_assistant_answer_duration_seconds_count", mode="search") == n + 2
    assert sample("ailadoc_assistant_no_results_total") == empty + 1
    assert sample("ailadoc_background_task_duration_seconds_count", task="assistant_index") > 0
    assert sample("ailadoc_assistant_index_documents") > 0


def test_limite_assistente_conteggiato(client, monkeypatch):
    monkeypatch.setattr(settings, "assistant_rate_per_minute", 1)
    login(client, "limitato", "ailadoc-viewer")
    token = csrf(client)
    before = sample("ailadoc_assistant_rate_limited_total")
    for _ in range(3):
        client.post("/api/assistant", json={"question": "ferie"}, headers={"x-csrf-token": token})
    assert sample("ailadoc_assistant_rate_limited_total") == before + 2


@pytest.mark.parametrize("status,outcome", [(200, "ok"), (500, "error")])
def test_durata_chiamata_llm(monkeypatch, status, outcome):
    def fake_post(u, **kw):
        return httpx.Response(status, json={"content": [{"type": "text", "text": "ciao"}]},
                              request=httpx.Request("POST", u))

    monkeypatch.setattr(settings, "assistant_llm", "anthropic")
    monkeypatch.setattr(settings, "assistant_api_key", "k")
    monkeypatch.setattr(settings, "assistant_model", "m")
    monkeypatch.setattr(settings, "assistant_base_url", "https://llm.test")
    monkeypatch.setattr(assistant.httpx, "post", fake_post)
    before = sample("ailadoc_llm_request_duration_seconds_count", provider="anthropic", outcome=outcome)
    if status == 200:
        assert assistant._call_llm("s", [{"role": "user", "content": "x"}]) == "ciao"
    else:
        with pytest.raises(assistant.LLMError):
            assistant._call_llm("s", [{"role": "user", "content": "x"}])
    assert sample("ailadoc_llm_request_duration_seconds_count", provider="anthropic", outcome=outcome) == before + 1


def test_timed_segna_errore():
    before = sample("ailadoc_keycloak_request_duration_seconds_count", operation="test", outcome="error")
    with pytest.raises(ValueError):
        with metrics.timed(metrics.KEYCLOAK_DURATION, operation="test", outcome="ok"):
            raise ValueError
    assert sample("ailadoc_keycloak_request_duration_seconds_count", operation="test", outcome="error") == before + 1
