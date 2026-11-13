"""Catalog + LAN distribution for built packs.

`packs catalog` scans a directory of .rfcpack files and writes catalog.json:

  {"generated_at": ..., "packs": [{"id","name","description","version",
    "doc_count","formats","file","size","sha256","generated_at"}]}

`packs serve` exposes that directory over plain HTTP so an Android app on
the same LAN can list and fetch packs:

  GET /                 -> tiny HTML listing
  GET /catalog.json     -> the catalog
  GET /packs/<file>     -> a .rfcpack download

sha256 is computed at catalog build time; the app re-verifies each download
before installing (same trust model as caionline's course packs).
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .builder import PACK_MARKER, PACK_SUFFIX

CATALOG_NAME = "catalog.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pack_info(pack_path: Path) -> dict:
    """Read the pack manifest out of the zip + compute file-level digest."""
    h = hashlib.sha256()
    with open(pack_path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    with zipfile.ZipFile(pack_path) as zf:
        roots = {n.split("/")[0] for n in zf.namelist() if "/" in n}
        if len(roots) != 1:
            raise ValueError(f"{pack_path.name}: not a single-root pack")
        root = next(iter(roots))
        with zf.open(f"{root}/{PACK_MARKER}") as fh:
            manifest = json.load(fh)
    return {
        "id": manifest["id"], "name": manifest.get("name", manifest["id"]),
        "description": manifest.get("description", ""),
        "version": manifest.get("version", ""),
        "generated_at": manifest.get("generated_at", ""),
        "doc_count": manifest.get("doc_count", 0),
        "chunk_count": manifest.get("chunk_count", 0),
        "formats": manifest.get("formats", []),
        "file": pack_path.name, "size": pack_path.stat().st_size,
        "sha256": h.hexdigest(),
    }


def write_catalog(packs_dir: Path) -> dict:
    packs_dir = Path(packs_dir)
    packs = [pack_info(p) for p in sorted(packs_dir.glob("*" + PACK_SUFFIX))]
    catalog = {"generated_at": _now(), "packs": packs}
    (packs_dir / CATALOG_NAME).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1), "utf-8")
    return catalog


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console readable
        if self.path != "/":
            super().log_message(fmt, *args)

    def _pack_target(self):
        name = self.path[len("/packs/"):]
        target = Path(self.directory) / Path(name).name
        if not target.is_file() or target.suffix != PACK_SUFFIX:
            return None
        return target

    def do_HEAD(self):  # noqa: N802
        if self.path.startswith("/packs/"):
            target = self._pack_target()
            if target is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.end_headers()
            return
        super().do_HEAD()

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            cat_path = Path(self.directory) / CATALOG_NAME
            catalog = (json.loads(cat_path.read_text("utf-8"))
                       if cat_path.is_file() else {"packs": []})
            rows = "".join(
                "<li><b><a href=\"/packs/{file}\">{name}</a></b> " \
                "({docs} docs, {mb:.1f} MB) — " \
                "<code>{sha}…</code></li>".format(
                    file=p["file"], name=p["name"], docs=p["doc_count"],
                    mb=p["size"] / 1e6, sha=p["sha256"][:16])
                for p in catalog.get("packs", []))
            body = (f"<html><body><h3>rfclib packs ({len(catalog.get('packs', []))})"
                    f"</h3><p>App → Sync → http://&lt;this host&gt;:{self.server.server_address[1]}</p>"
                    f"<ul>{rows}</ul></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/packs/"):
            target = self._pack_target()
            if target is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Content-Disposition",
                             f"attachment; filename=\"{target.name}\"")
            self.end_headers()
            with open(target, "rb") as fh:
                while blk := fh.read(1 << 20):
                    self.wfile.write(blk)
            return
        super().do_GET()


def serve(packs_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    packs_dir = Path(packs_dir)
    if not (packs_dir / CATALOG_NAME).is_file():
        write_catalog(packs_dir)
    httpd = ThreadingHTTPServer(
        (host, port), partial(_Handler, directory=str(packs_dir)))
    return httpd
