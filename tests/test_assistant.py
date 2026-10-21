"""Assistente: ricerca nei vari formati, permessi, CSRF, LLM (simulato) e fallback."""
import pytest

from app import assistant
from app.config import settings
from conftest import csrf, login

HR = "04-Risorse-Umane"


def ask(c, question, history=None, token=None):
    token = token or csrf(c)
    return c.post("/api/assistant", json={"question": question, "history": history or []},
                  headers={"x-csrf-token": token})


def paths(r):
    return [s["path"] for s in r.json()["sources"]]


def test_serve_login_e_ruolo(client):
    r = client.post("/api/assistant", json={"question": "ferie"}, follow_redirects=False)
    assert r.status_code in (303, 403) and "sources" not in r.text
    login(client, "nobody", "")
    r = client.post("/api/assistant", json={"question": "ferie"}, headers={"x-csrf-token": "x"})
    assert r.status_code == 403


def test_csrf_obbligatorio(client):
    login(client, "viewer", "ailadoc-viewer")
    r = client.post("/api/assistant", json={"question": "ferie"})
    assert r.status_code == 403


def test_pannello_nella_pagina(client):
    login(client, "viewer", "ailadoc-viewer")
    html = client.get("/").text
    assert 'id="assistant"' in html and "assistant.js" in html and "Chiedi a AIla" in html


def test_trova_pagina_markdown(client):
    login(client, "viewer", "ailadoc-viewer")
    r = ask(client, "Con quanti giorni di anticipo devo chiedere le ferie?")
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "search"
    assert d["sources"][0]["path"] == f"{HR}/policy-ferie.md"
    assert "<mark>ferie</mark>" in d["sources"][0]["snippet_html"]
    assert 'class="cite"' in d["answer_html"]


@pytest.mark.parametrize("question,expected,anchor", [
    ("prezzo del sensore di temperatura", "03-Commerciale/listino-2026.xlsx", "?sheet=Listino"),
    ("fatturato dei clienti di Torino", "03-Commerciale/clienti-esempio.csv", ""),
    ("registrare le non conformità nel manuale", "02-Procedure/Qualit%C3%A0/manuale-qualita.pdf", "?page=3"),
    ("modulo con descrizione del problema e azione correttiva", "02-Procedure/Qualità/modulo-non-conformita.docx", ""),
    ("offerta gateway LoRa", "03-Commerciale/presentazione-2026.pptx", "?page="),
    ("come si accede con l'account aziendale", "01-Guida/01-primi-passi.md", "#accesso"),
])
def test_trova_dentro_i_formati(client, question, expected, anchor):
    login(client, "viewer", "ailadoc-viewer")
    src = ask(client, question).json()["sources"][0]
    assert src["path"].replace("à", "%C3%A0") == expected.replace("à", "%C3%A0")
    assert anchor in src["url"]


def test_nessun_risultato(client):
    login(client, "viewer", "ailadoc-viewer")
    d = ask(client, "zxqwv kkjjhh").json()
    assert d["sources"] == [] and "Non ho trovato" in d["answer"]


def test_rispetta_i_permessi(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "restrict"})
    assert f"{HR}/policy-ferie.md" in paths(ask(client, "ferie", token=token))  # admin vede tutto
    login(client, "vera", "ailadoc-viewer")
    d = ask(client, "richieste di ferie 15 giorni").json()
    assert all(not p.startswith(HR) for p in [s["path"] for s in d["sources"]])
    assert "15 giorni" not in d["answer_html"]


def test_documento_nuovo_indicizzato(client, data_dir):
    login(client, "viewer", "ailadoc-viewer")
    assert ask(client, "parcheggio").json()["sources"] == []
    (data_dir / "docs/01-Guida/parcheggio.md").write_text("# Parcheggio\n\nIl parcheggio aziendale è al piano -1.\n")
    assert paths(ask(client, "dove si trova il parcheggio aziendale?"))[0] == "01-Guida/parcheggio.md"


def test_llm_riceve_solo_documenti_visibili(client, monkeypatch):
    calls = []

    def fake_llm(system, messages):
        calls.append(messages)
        return "Le ferie vanno chieste con **15 giorni** di anticipo [1]."

    monkeypatch.setattr(settings, "assistant_llm", "anthropic")
    monkeypatch.setattr(settings, "assistant_api_key", "test")
    monkeypatch.setattr(assistant, "_call_llm", fake_llm)

    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "restrict"})
    login(client, "viewer", "ailadoc-viewer")
    ask(client, "policy ferie giorni di anticipo")
    assert all("15 giorni" not in m["content"] for msgs in calls for m in msgs)

    login(client, "admin", "ailadoc-admin")
    calls.clear()
    d = ask(client, "policy ferie giorni di anticipo",
            history=[{"role": "user", "content": "ciao"}, {"role": "assistant", "content": "ciao!"}]).json()
    assert d["mode"] == "ai"
    ctx = calls[0][-1]["content"]
    assert "<documenti>" in ctx and "15 giorni" in ctx
    assert [m["role"] for m in calls[0]] == ["user", "assistant", "user"]
    assert '<a class="cite" href="/d/04-Risorse-Umane/policy-ferie.md"' in d["answer_html"]
    assert "<strong>15 giorni</strong>" in d["answer_html"]


def test_llm_non_raggiungibile_fallback(client, monkeypatch):
    def broken(system, messages):
        raise assistant.LLMError("timeout")

    monkeypatch.setattr(settings, "assistant_llm", "anthropic")
    monkeypatch.setattr(settings, "assistant_api_key", "test")
    monkeypatch.setattr(assistant, "_call_llm", broken)
    login(client, "viewer", "ailadoc-viewer")
    d = ask(client, "gestione dei resi").json()
    assert d["mode"] == "search" and d["notice"] and d["sources"]


def test_risposta_llm_sanificata(client, monkeypatch):
    monkeypatch.setattr(settings, "assistant_llm", "anthropic")
    monkeypatch.setattr(settings, "assistant_api_key", "test")
    monkeypatch.setattr(assistant, "_call_llm", lambda s, m: '<script>alert(1)</script><img src=x onerror=alert(2)> ok [1]')
    login(client, "viewer", "ailadoc-viewer")
    h = ask(client, "gestione dei resi").json()["answer_html"]
    assert "<script" not in h and "onerror" not in h and 'class="cite"' in h


def test_limite_richieste(client, monkeypatch):
    monkeypatch.setattr(settings, "assistant_rate_per_minute", 2)
    assistant._hits.clear()
    login(client, "viewer", "ailadoc-viewer")
    token = csrf(client)
    assert ask(client, "resi", token=token).status_code == 200
    assert ask(client, "resi", token=token).status_code == 200
    assert ask(client, "resi", token=token).status_code == 429


def test_link_a_pagina_e_foglio(client):
    login(client, "viewer", "ailadoc-viewer")
    html = client.get("/d/02-Procedure/Qualit%C3%A0/manuale-qualita.pdf?page=3").text
    assert "#page=3&view=FitH" in html
    html = client.get("/d/03-Commerciale/listino-2026.xlsx?sheet=Sconti").text
    assert 'class="tab active" data-tab="sheet-2"' in html


def test_stemming_italiano():
    t = assistant.tokens
    assert t("ferie") == t("feria")
    assert t("reso") == t("resi")
    assert set(t("conformità")) == set(t("conformita"))


@pytest.mark.parametrize("provider,url,reply", [
    ("anthropic", "https://api.anthropic.com/v1/messages",
     {"content": [{"type": "text", "text": "Vedi il manuale [1]."}]}),
    ("openai", "http://ollama:11434/v1/chat/completions",
     {"choices": [{"message": {"content": "Vedi il manuale [1]."}}]}),
])
def test_chiamata_http_ai_provider(monkeypatch, provider, url, reply):
    import httpx
    seen = {}

    def fake_post(u, headers=None, json=None, timeout=None):
        seen.update(url=u, headers=headers, json=json)
        return httpx.Response(200, json=reply, request=httpx.Request("POST", u))

    monkeypatch.setattr(settings, "assistant_llm", provider)
    monkeypatch.setattr(settings, "assistant_api_key", "k" if provider == "anthropic" else "")
    monkeypatch.setattr(settings, "assistant_model", "m")
    monkeypatch.setattr(settings, "assistant_base_url",
                        "https://api.anthropic.com" if provider == "anthropic" else "http://ollama:11434/v1")
    monkeypatch.setattr(assistant.httpx, "post", fake_post)
    assert assistant._call_llm("sys", [{"role": "user", "content": "q"}]) == "Vedi il manuale [1]."
    assert seen["url"] == url and seen["json"]["model"] == "m"
    if provider == "anthropic":
        assert seen["headers"]["x-api-key"] == "k" and seen["json"]["system"] == "sys"
    else:
        assert seen["json"]["messages"][0] == {"role": "system", "content": "sys"}
