"""Creazione rapida di pagine, cartelle annidate e strutture."""
from conftest import csrf, login

from app.creator import page_filename, slugify


def create(client, token, **body):
    return client.post("/api/create", json=body, headers={"x-csrf-token": token})


def test_slug():
    assert slugify("Qualità & Sicurezza!") == "qualita-sicurezza"
    assert page_filename("01 Introduzione") == "01-introduzione.md"
    assert page_filename("???") == "pagina.md"


def test_pagina_con_percorso_annidato(client, data_dir):
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    r = create(client, token, parent="01-Guida", mode="page", title="Procedure/Qualità/Controllo accessi")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["created"] == 3 and d["url"] == "/edit/01-Guida/Procedure/Qualit%C3%A0/controllo-accessi.md"
    p = data_dir / "docs/01-Guida/Procedure/Qualità/controllo-accessi.md"
    assert p.read_text() == "# Controllo accessi\n\n"
    # la pagina compare nel menu con il suo titolo
    assert "Controllo accessi" in client.get("/").text


def test_prefisso_ordine_e_duplicati(client, data_dir):
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    assert create(client, token, parent="", mode="page", title="05 Glossario").status_code == 200
    assert (data_dir / "docs/05-glossario.md").read_text() == "# Glossario\n\n"
    r = create(client, token, parent="", mode="page", title="05 Glossario")
    assert r.status_code == 409 and "Esiste già" in r.json()["error"]


def test_cartella_con_indice(client, data_dir):
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    r = create(client, token, parent="", mode="folder", title="06-Manuali/Software", index=True)
    assert r.status_code == 200 and r.json()["url"] == "/d/06-Manuali/Software"
    assert (data_dir / "docs/06-Manuali/Software/index.md").read_text() == "# Software\n\n"
    assert not (data_dir / "docs/06-Manuali/index.md").exists()  # solo la cartella finale


def test_struttura_in_blocco(client, data_dir):
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    text = """
Manuale/
  Installazione
  Configurazione
    - Rete
    - Utenti
- Domande frequenti
"""
    r = create(client, token, parent="01-Guida", mode="tree", text=text, index=True)
    assert r.status_code == 200, r.text
    base = data_dir / "docs/01-Guida"
    assert (base / "Manuale/index.md").exists()
    assert (base / "Manuale/installazione.md").exists()
    # "Configurazione" ha righe rientrate sotto -> è una cartella
    assert (base / "Manuale/Configurazione").is_dir()
    assert (base / "Manuale/Configurazione/rete.md").exists()
    assert (base / "Manuale/Configurazione/utenti.md").exists()
    assert (base / "domande-frequenti.md").exists()
    # ripetere la stessa struttura non crea duplicati
    r = create(client, token, parent="01-Guida", mode="tree", text=text)
    assert r.json()["created"] == 0


def test_permessi_e_percorsi_non_validi(client, data_dir):
    login(client, "viewer", "ailadoc-viewer")
    token = csrf(client)
    assert create(client, token, parent="", mode="page", title="x").status_code == 403

    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    for title in ("../fuori", "a/../../b", "/", "   "):
        r = create(client, token, parent="", mode="page", title=title)
        assert r.status_code == 400, title
    assert create(client, token, parent="../etc", mode="page", title="x").status_code == 400
    assert not (data_dir / "fuori.md").exists() and not (data_dir.parent / "fuori.md").exists()
    assert create(client, token, parent="", mode="page", title="x").status_code == 200
    # senza CSRF
    assert client.post("/api/create", json={"mode": "page", "title": "y"}).status_code == 403


def test_cartella_ristretta_in_sola_lettura(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/permissions", data={"csrf": token, "path": "01-Guida", "action": "restrict"})
    client.post("/admin/permissions", data={"csrf": token, "path": "01-Guida", "action": "add",
                                            "principal_type": "app_role", "value_app_role": "Editor", "level": "view"})
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    r = create(client, token, parent="01-Guida", mode="page", title="Nuova")
    assert r.status_code == 400 and "permessi" in r.json()["error"]
    html = client.get("/").text
    assert 'data-parent="01-Guida"' not in html  # niente "+" sulla cartella in sola lettura
    assert 'class="sidebar-new"' in html


def test_dialogo_presente_solo_per_editor(client):
    login(client, "viewer", "ailadoc-viewer")
    assert 'id="dlg-create"' not in client.get("/").text
    login(client, "editor", "ailadoc-editor")
    html = client.get("/d/01-Guida/01-primi-passi.md").text
    assert 'id="dlg-create"' in html
    assert '<option value="01-Guida" selected>' in html  # cartella corrente proposta di default
