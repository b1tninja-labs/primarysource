"""Kiwix ZIM export: one collection -> one .zim archive.

Uses the official ``libzim`` bindings (optional extra: ``uv sync --extra
zim``), imported lazily so the rest of rfclib works without the native
wheel. Articles live at lowercase paths (``rfc9000``) and are rendered
by the shared export.py layer — the exact same pages as the EPUB/HTML
exports, with cross-reference links rewritten to ZIM paths.

libzim builds a Xapian full-text index and a title-suggestion index at
write time (``config_indexing``), so Kiwix-serve / Kiwix apps get offline
full-text search and type-ahead suggestions over the corpus for free.
"""
from __future__ import annotations

import html as htmllib
import importlib.util
import os
import shutil
import stat
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .collections import Collection
from .export import ExportDoc, STYLE_CSS, make_resolver, render_doc_page

HAVE_LIBZIM = importlib.util.find_spec("libzim") is not None

MIMETYPE_HTML = "text/html"
MIMETYPE_CSS = "text/css"


def _png_illustration(size: int = 48) -> bytes:
    """Minimal valid PNG (stdlib only): page icon with text lines."""
    bg, fg = (31, 41, 55), (229, 231, 235)
    bars = [(10, 14, 8, 40), (17, 21, 8, 40), (24, 28, 8, 40), (31, 35, 8, 28)]
    raw = b"".join(
        b"\x00" + b"".join(
            bytes(fg if any(y0 <= y < y1 and x0 <= x < x1
                            for y0, y1, x0, x1 in bars) else bg)
            for x in range(size))
        for y in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _index_page(coll: Collection, docs: list[ExportDoc]) -> str:
    rows = "".join(
        "<tr>"
        f'<td class="num"><a href="{htmllib.escape(d.doc_id.lower())}">'
        f"{htmllib.escape(d.doc_id)}</a></td>"
        f"<td>{htmllib.escape(d.title)}</td>"
        f"<td>{htmllib.escape(d.status)}</td>"
        f'<td class="num">{htmllib.escape(d.pub_date)}</td>'
        f"<td>{'current' if d.current else 'obsolete'}</td>"
        "</tr>" for d in docs)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{htmllib.escape(coll.name)} — rfclib ZIM</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h1>{htmllib.escape(coll.name)}</h1>
<p class="meta">{len(docs)} documents · rfclib ZIM export · full-text search
via Kiwix</p>
<p>{htmllib.escape(coll.description)}</p>
<table class="index">
<tr><th>Doc</th><th>Title</th><th>Status</th><th>Published</th><th></th></tr>
{rows}
</table>
</body>
</html>
"""


def _unseal_remove(func, path, exc):
    """rmtree onerror: Xapian seals scratch read-only; clear and retry once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def build_zim(coll: Collection, docs: list[ExportDoc], out_dir: Path,
              link_refs: str = "internal",
              progress: Optional[Callable[[str], None]] = None) -> dict:
    """Write <out_dir>/<coll.id>.zim; returns a summary dict (build_html shape)."""
    if not HAVE_LIBZIM:
        raise ImportError("zim export requires the optional extra: "
                          "uv sync --extra zim")
    import libzim.writer as lw

    known = {d.doc_id: d.doc_id.lower() for d in docs}
    resolver = make_resolver(known, link_refs)
    zim_path = Path(out_dir) / f"{coll.id}.zim"
    zim_path.parent.mkdir(parents=True, exist_ok=True)

    class _Item(lw.Item):
        def __init__(self, path, title, mimetype, content, front):
            self._p, self._t, self._m = path, title, mimetype
            self._c, self._front = content, front

        def get_path(self):
            return self._p

        def get_title(self):
            return self._t

        def get_mimetype(self):
            return self._m

        def get_contentprovider(self):
            return lw.StringProvider(self._c)

        def get_hints(self):
            return {lw.Hint.COMPRESS: True,
                    lw.Hint.FRONT_ARTICLE: self._front}

    creator = (lw.Creator(str(zim_path))
               .config_compression(lw.Compression.zstd)
               .config_indexing(True, "eng")
               .config_verbose(False))
    creator.set_mainpath("index")  # config-time only; validated at finish
    with creator:
        creator.add_metadata("Name", coll.id)
        creator.add_metadata("Title", coll.name)
        creator.add_metadata("Description", coll.description)
        creator.add_metadata("Language", "eng")
        creator.add_metadata("Creator", "rfclib")
        creator.add_metadata("Publisher", "rfclib")
        creator.add_metadata("Date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        creator.add_metadata("Tags", "rfc;standards;internet")
        creator.add_illustration(48, _png_illustration(48))
        creator.add_item(_Item("index", coll.name, MIMETYPE_HTML,
                               _index_page(coll, docs), front=False))
        creator.add_item(_Item("style.css", "", MIMETYPE_CSS, STYLE_CSS,
                               front=False))
        for n, doc in enumerate(docs, 1):
            page, _heads = render_doc_page(doc, resolver,
                                           css_href="style.css",
                                           back_href="index")
            creator.add_item(_Item(known[doc.doc_id],
                                   f"{doc.doc_id}: {doc.title}",
                                   MIMETYPE_HTML, page, front=True))
            if progress:
                progress(f"zim {n}/{len(docs)} {doc.doc_id}")
    # libzim leaves Xapian scratch next to the archive after finish() (sealed
    # read-only on Windows — files and whole .idx.tmp dirs): sweep them.
    for scratch in zim_path.parent.glob(f"{zim_path.name}*idx*"):
        try:
            if scratch.is_dir():
                shutil.rmtree(scratch, onerror=_unseal_remove)
            else:
                os.chmod(scratch, stat.S_IWRITE)
                scratch.unlink()
        except OSError:
            pass
    return {"id": coll.id, "format": "zim", "path": str(zim_path),
            "docs": len(docs), "bytes": zim_path.stat().st_size}
