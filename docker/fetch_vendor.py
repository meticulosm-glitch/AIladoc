#!/usr/bin/env python3
"""Scarica le librerie JavaScript servite in locale da /static/vendor (nessun CDN a runtime).

    python docker/fetch_vendor.py            # dalla radice del progetto, per lo sviluppo
    python docker/fetch_vendor.py --dest /app/app/static/vendor   # usato dal Dockerfile

- mermaid       diagrammi ```mermaid
- katex         formule LaTeX (macro /// latex e $...$)
- draw.io       visualizzatore dei diagrammi .drawio (viewer-static.min.js)

Le versioni si possono cambiare con le variabili MERMAID_VERSION, KATEX_VERSION, DRAWIO_VERSION.
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

MERMAID = os.getenv("MERMAID_VERSION", "11.4.1")
KATEX = os.getenv("KATEX_VERSION", "0.16.22")
DRAWIO = os.getenv("DRAWIO_VERSION", "32.5.5")


def get(url: str) -> bytes:
    print(f"  ↓ {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ailadoc-build"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def npm_tarball(name: str, version: str) -> tarfile.TarFile:
    return tarfile.open(fileobj=io.BytesIO(get(f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz")), mode="r:gz")


def extract(tar: tarfile.TarFile, prefix: str, dest: Path) -> int:
    n = 0
    for m in tar.getmembers():
        if not m.isfile() or not m.name.startswith(prefix):
            continue
        rel = m.name[len(prefix):].lstrip("/")
        if not rel or ".." in Path(rel).parts:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with tar.extractfile(m) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=str(Path(__file__).resolve().parents[1] / "app" / "static" / "vendor"))
    ap.add_argument("--skip", default="", help="elenco separato da virgole: mermaid,katex,drawio")
    args = ap.parse_args()
    dest = Path(args.dest)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    dest.mkdir(parents=True, exist_ok=True)

    if "mermaid" not in skip:
        print(f"mermaid {MERMAID}")
        tar = npm_tarball("mermaid", MERMAID)
        data = tar.extractfile("package/dist/mermaid.min.js").read()
        (dest / "mermaid.min.js").write_bytes(data)

    if "katex" not in skip:
        print(f"katex {KATEX}")
        kdir = dest / "katex"
        if kdir.exists():
            shutil.rmtree(kdir)
        tar = npm_tarball("katex", KATEX)
        n = 0
        for name in ("katex.min.js", "katex.min.css"):
            out = kdir / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tar.extractfile(f"package/dist/{name}").read())
            n += 1
        n += extract(tar, "package/dist/fonts", kdir / "fonts")
        print(f"  {n} file")

    if "drawio" not in skip:
        print(f"draw.io viewer {DRAWIO}")
        ddir = dest / "drawio"
        ddir.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/jgraph/drawio/v{DRAWIO}/src/main/webapp/js/viewer-static.min.js"
        (ddir / "viewer-static.min.js").write_bytes(get(url))

    print(f"Fatto: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
