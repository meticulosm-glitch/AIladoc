import os
import stat

from app.config import _secret_key


def test_secret_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECRET_KEY", "dall-ambiente")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert _secret_key() == "dall-ambiente"
    assert not (tmp_path / ".secret_key").exists()


def test_secret_key_generated_once_and_persisted(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    first = _secret_key()
    assert len(first) >= 48
    path = data / ".secret_key"
    assert path.read_text() == first
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # riavvio (o seconda replica sullo stesso volume): stessa chiave
    assert _secret_key() == first


def test_secret_key_unwritable_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv("DATA_DIR", str(blocker / "data"))  # il genitore è un file: mkdir fallisce
    assert len(_secret_key()) >= 48
