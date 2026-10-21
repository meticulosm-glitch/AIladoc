from conftest import csrf, login

DOC = "/d/01-Guida/01-primi-passi.md"
HR = "04-Risorse-Umane"


def test_anonimo_va_al_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_utente_senza_ruoli_vede_deny(client):
    login(client, "nobody", "")
    for url in ("/", DOC, "/raw/index.md", "/search?q=a"):
        r = client.get(url)
        assert r.status_code == 403, url
        assert "Accesso negato" in r.text
    assert "Primi passi" not in client.get("/").text  # nessun menu


def test_ruolo_sconosciuto_vede_deny(client):
    login(client, "x", "qualcosa-altro")
    assert client.get("/").status_code == 403


def test_lettore_legge_ma_non_modifica(client):
    login(client, "viewer", "ailadoc-viewer")
    r = client.get(DOC)
    assert r.status_code == 200 and "Primi passi" in r.text
    assert "/edit/" not in r.text
    assert client.get("/edit/01-Guida/01-primi-passi.md").status_code == 403
    token = csrf(client)
    r = client.post("/edit/01-Guida/01-primi-passi.md", data={"csrf": token, "content": "x"})
    assert r.status_code == 403
    assert client.get("/admin/roles").status_code == 403


def test_editor_modifica_e_carica(client, data_dir):
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    r = client.post("/edit/01-Guida/01-primi-passi.md", data={"csrf": token, "content": "# Nuovo titolo\n"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert (data_dir / "docs/01-Guida/01-primi-passi.md").read_text() == "# Nuovo titolo\n"
    r = client.post("/upload", data={"csrf": token, "folder": "03-Commerciale"},
                    files=[("files", ("note.pdf", b"%PDF-1.4 test", "application/pdf"))], follow_redirects=False)
    assert r.status_code == 303
    assert (data_dir / "docs/03-Commerciale/note.pdf").exists()
    # tipo non ammesso
    r = client.post("/upload", data={"csrf": token, "folder": ""}, headers={"accept": "application/json"},
                    files=[("files", ("evil.html", b"<script>", "text/html"))])
    assert r.json()["errors"] and not (data_dir / "docs/evil.html").exists()
    # cartella, nuova pagina, spostamento, eliminazione
    client.post("/mkdir", data={"csrf": token, "folder": "", "name": "05-Nuova"})
    assert (data_dir / "docs/05-Nuova").is_dir()
    client.post("/new", data={"csrf": token, "folder": "05-Nuova", "filename": "pagina", "content": "# P"})
    assert (data_dir / "docs/05-Nuova/pagina.md").exists()
    client.post("/move", data={"csrf": token, "path": "05-Nuova/pagina.md", "dest_folder": "01-Guida", "new_name": "spostata.md"})
    assert (data_dir / "docs/01-Guida/spostata.md").exists()
    client.post("/delete", data={"csrf": token, "path": "05-Nuova"})
    assert not (data_dir / "docs/05-Nuova").exists()


def test_csrf_obbligatorio(client):
    login(client, "editor", "ailadoc-editor")
    r = client.post("/edit/01-Guida/01-primi-passi.md", data={"content": "x"})
    assert r.status_code == 403


def test_restrizione_cartella_e_gruppo_locale(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    # gruppo locale HR con mario
    client.post("/admin/groups", data={"csrf": token, "name": "HR", "members": "Mario.Rossi\n"})
    # restringi la cartella al gruppo HR in lettura
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "restrict"})
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "add",
                                            "principal_type": "group", "value_group": "HR", "level": "view"})
    # admin vede comunque
    assert client.get(f"/d/{HR}/policy-ferie.md").status_code == 200

    # un lettore qualsiasi non vede né la cartella né il file, e non compare nel menu
    login(client, "vera", "ailadoc-viewer")
    assert client.get(f"/d/{HR}/policy-ferie.md").status_code == 403
    assert client.get(f"/raw/{HR}/policy-ferie.md").status_code == 403
    assert "Risorse Umane" not in client.get("/d/01-Guida").text
    assert "ferie" not in client.get("/search?q=ferie").text.lower().split("risultati per")[1].split("</h1>")[1]

    # mario (membro del gruppo) la vede in sola lettura anche se è editor globale
    login(client, "mario.rossi", "ailadoc-editor")
    r = client.get(f"/d/{HR}/policy-ferie.md")
    assert r.status_code == 200 and "/edit/" not in r.text
    assert client.get(f"/edit/{HR}/policy-ferie.md").status_code == 403


def test_tetto_del_ruolo_keycloak(client):
    """Un'ACL 'edit' non trasforma un lettore in editor."""
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "restrict"})
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "add",
                                            "principal_type": "user", "value_user": "vera", "level": "edit"})
    login(client, "vera", "ailadoc-viewer")
    assert client.get(f"/d/{HR}/policy-ferie.md").status_code == 200
    assert client.get(f"/edit/{HR}/policy-ferie.md").status_code == 403


def test_restrizione_piu_profonda_vince(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/permissions", data={"csrf": token, "path": HR, "action": "restrict"})
    f = f"{HR}/policy-ferie.md"
    client.post("/admin/permissions", data={"csrf": token, "path": f, "action": "restrict"})
    client.post("/admin/permissions", data={"csrf": token, "path": f, "action": "add",
                                            "principal_type": "app_role", "value_app_role": "Lettori", "level": "view"})
    login(client, "vera", "ailadoc-viewer")
    assert client.get(f"/d/{HR}/index.md").status_code == 403
    assert client.get(f"/d/{f}").status_code == 200
    # la cartella compare nel menu (come contenitore) perché contiene un file visibile
    assert "Policy ferie 2026" in client.get("/").text


def test_ruolo_app_da_ruolo_keycloak_personalizzato(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    client.post("/admin/roles", data={"csrf": token, "name": "Commerciali", "keycloak_roles": "sales, crm:user",
                                      "global_level": "view"})
    login(client, "luca", "crm:user")
    assert client.get(DOC).status_code == 200


def test_path_traversal(client):
    login(client, "admin", "ailadoc-admin")
    for url in ("/raw/..%2f..%2fetc%2fpasswd", "/d/../../etc/passwd", "/raw/.hidden", "/d/%2e%2e/x"):
        r = client.get(url)
        assert r.status_code in (403, 404), url
        assert "root:" not in r.text


def test_markdown_sanificato_e_link_riscritti(client, data_dir):
    (data_dir / "docs/01-Guida/xss.md").write_text(
        '# T\n\n<script>alert(1)</script>\n<img src=x onerror="alert(2)">\n'
        '[link](01-primi-passi.md#accesso) ![img](../img/a.png) [js](javascript:alert(3))\n')
    login(client, "viewer", "ailadoc-viewer")
    html = client.get("/d/01-Guida/xss.md").text
    body = html.split('class="md-content"')[1]
    assert "<script>alert" not in body and "onerror" not in body and "javascript:" not in body
    assert 'href="/d/01-Guida/01-primi-passi.md#accesso"' in body
    assert 'src="/raw/img/a.png"' in body


def test_svg_servito_in_sandbox(client, data_dir):
    (data_dir / "docs/a.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    login(client, "viewer", "ailadoc-viewer")
    r = client.get("/raw/a.svg")
    assert r.status_code == 200 and "sandbox" in r.headers["content-security-policy"]


def test_anteprima_excel_e_csv(client):
    login(client, "viewer", "ailadoc-viewer")
    r = client.get("/d/03-Commerciale/listino-2026.xlsx")
    assert "Sensore temperatura" in r.text and "Sconti" in r.text
    r = client.get("/d/03-Commerciale/clienti-esempio.csv")
    assert "Alfa Srl" in r.text


def test_icone_per_tipo_nel_menu(client):
    login(client, "viewer", "ailadoc-viewer")
    html = client.get("/d/03-Commerciale").text
    for kind in ("ic-sheet", "ic-slides", "ic-folder"):
        assert kind in html
    html = client.get("/d/02-Procedure/Qualit%C3%A0/manuale-qualita.pdf").text
    assert "ic-pdf" in html and "ic-word" in html


def test_admin_env_non_si_chiude_fuori(client):
    login(client, "admin", "ailadoc-admin")
    token = csrf(client)
    from app import db as dbm
    from sqlalchemy import select
    with dbm.SessionLocal() as s:
        ids = [r.id for r in s.scalars(select(dbm.AppRole))]
    for rid in ids:
        client.post(f"/admin/roles/{rid}/delete", data={"csrf": token})
    assert client.get("/admin/roles").status_code == 200
