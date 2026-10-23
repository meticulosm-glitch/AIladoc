"""Immagini: tre dimensioni scelte nell'editor e link a file con spazi o parentesi nel nome."""
from conftest import csrf, login

from app.render import render_markdown

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def _html(md: str) -> str:
    return render_markdown(md, "01-Guida/pagina.md", use_plugins=False)[0]


def test_dimensioni_immagine_come_classe():
    for size in ("piccola", "media", "grande"):
        assert f'class="img-{size}"' in _html(f"![foto](foto.png){{ .img-{size} }}")
    # altri attributi restano, quelli pericolosi no
    html = _html('![a](a.png){ .img-media width="300" onerror="alert(1)" }')
    assert 'class="img-media"' in html and 'width="300"' in html and "onerror" not in html


def test_nomi_con_spazi_e_parentesi_non_codificati_due_volte():
    html = _html("![a](foto%20uno.png) ![b](foto%20%281%29.png) ![c](<foto due.png>) [pdf](Manuale%20qualit%C3%A0.pdf)")
    assert 'src="/raw/01-Guida/foto%20uno.png"' in html
    assert 'src="/raw/01-Guida/foto%20%281%29.png"' in html
    assert 'src="/raw/01-Guida/foto%20due.png"' in html
    assert 'href="/d/01-Guida/Manuale%20qualit%C3%A0.pdf"' in html
    assert "%25" not in html


def test_immagine_caricata_con_spazi_si_vede(client, data_dir):
    login(client, "editor", "ailadoc-editor")
    token = csrf(client)
    r = client.post("/upload", data={"csrf": token, "folder": "01-Guida"}, headers={"accept": "application/json"},
                    files=[("files", ("Schermata 2026 (1).png", PNG, "image/png"))])
    assert r.json()["saved"] == ["01-Guida/Schermata 2026 (1).png"]
    # il Markdown che scrive l'editor (encodeURIComponent + parentesi codificate)
    (data_dir / "docs/01-Guida/foto.md").write_text("# F\n\n![Schermata](Schermata%202026%20%281%29.png){ .img-piccola }\n")
    body = client.get("/d/01-Guida/foto.md").text.split('class="md-content"')[1]
    src = body.split('<img', 1)[1].split('src="', 1)[1].split('"', 1)[0]
    assert 'class="img-piccola"' in body
    r = client.get(src)
    assert r.status_code == 200 and r.content == PNG
