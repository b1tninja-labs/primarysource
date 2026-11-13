"""Dash docset export: one collection -> one <id>.docset bundle (+ .tgz).

Canonical docset layout (Dash / Xcode / Zeal all read it):

  <id>.docset/Contents/
    Info.plist                    bundle identity, Dash/Xcode keys
    Resources/
      icon.png                    32x32 catalogue icon (generated, stdlib)
      docSet.dsidx                SQLite searchIndex(word, type, url)
      Documents/                  index.html + style.css + RFCxxxx.html

Pages come from the shared export.py render layer — identical to the
EPUB/HTML/ZIM exports — laid out flat in Documents/. The dsidx gives
Dash its headline feature: type-ahead lookup of documents ("RFC9110…")
and top-level sections ("RFC9110: 4.2. HTTP Messaging") that deep-link
straight into the section anchor. No new dependencies: plistlib,
sqlite3 and tarfile are stdlib.
"""
from __future__ import annotations

import html as htmllib
import plistlib
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .collections import Collection
from .export import ExportDoc, STYLE_CSS, make_resolver, render_doc_page
from .zimexport import _png_illustration  # stdlib PNG generator, no libzim

# Section headings at or above this level (smaller = shallower) become
# index entries; level 2 is what the renderer gives top-level numbered
# sections and appendices, so this is "one entry per section".
MAX_INDEX_LEVEL = 2


def _index_page(coll: Collection, docs: list[ExportDoc], now: str) -> str:
    rows = "".join(
        "<tr>"
        f'<td class="num"><a href="{htmllib.escape(d.doc_id)}.html">'
        f"{htmllib.escape(d.doc_id)}</a></td>"
        f"<td>{htmllib.escape(d.title)}</td>"
        f"<td>{htmllib.escape(d.status)}</td>"
        f'<td class="num">{htmllib.escape(d.pub_date)}</td>'
        f"{'current' if d.current else 'obsolete'}"
        "</tr>" for d in docs)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{htmllib.escape(coll.name)} — rfclib docset</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h1>{htmllib.escape(coll.name)}</h1>
<p class="meta">{len(docs)} documents · generated {now} · Dash docset
(lookup via Dash; anchors link into sections)</p>
<p>{htmllib.escape(coll.description)}</p>
<table class="index">
<tr><th>Doc</th><th>Title</th><th>Status</th><th>Published</th><th></th></tr>
{rows}
</table>
</body>
</html>
"""


def _info_plist(coll: Collection, now: str) -> dict:
    return {
        "CFBundleIdentifier": f"org.rfclib.{coll.id}",
        "CFBundleName": coll.name,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleIconFile": "icon.png",
        # Xcode reads docset_platform; Dash ignores unknown keys.
        "docset_platform": {
            "platform_family": "Common",
            "docset_name": coll.id,
            "dashboard_name": coll.name,
            "docset_article_path": "Documents",
        },
        # Dash-specific markers.
        "isDashDocset": True,
        "dashDocsetCompat": ["Common"],
        "docset_icon": "icon.png",
        "docset_taxonomy": "guides;reference;standards",
        "dash_docset_date": now,
    }


def _build_dsidx(db_path: Path, docs: list[ExportDoc],
                 toc: dict[str, list[tuple[int, str, str]]]) -> int:
    """Write the searchIndex table; returns the number of index rows."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS searchIndex;"
            "CREATE TABLE searchIndex(id INTEGER PRIMARY KEY,"
            " word TEXT, type TEXT, url TEXT);"
            "CREATE INDEX word ON searchIndex (word);")
        rows: list[tuple[str, str, str]] = []
        for doc in docs:
            fname = f"{doc.doc_id}.html"
            rows.append((f"{doc.doc_id}: {doc.title}", "Guide", fname))
            for level, hid, text in toc.get(doc.doc_id, []):
                if level > MAX_INDEX_LEVEL or hid.startswith("toc"):
                    continue
                rows.append((f"{doc.doc_id}: {text}", "Section",
                             f"{fname}#{hid}"))
        conn.executemany(
            "INSERT INTO searchIndex(word, type, url) VALUES (?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def build_docset(coll: Collection, docs: list[ExportDoc], out_dir: Path,
                 link_refs: str = "internal",
                 progress: Optional[Callable[[str], None]] = None) -> dict:
    """Write <out_dir>/<coll.id>.docset (+ .tgz); summary dict like build_html."""
    root = Path(out_dir) / f"{coll.id}.docset"
    res_dir = root / "Contents" / "Resources"
    docs_dir = res_dir / "Documents"
    # Stale files must not survive a rebuild — Dash would keep dead entries.
    if root.exists():
        shutil.rmtree(root)
    docs_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    known = {d.doc_id: f"{d.doc_id}.html" for d in docs}
    resolver = make_resolver(known, link_refs)

    (root / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(_info_plist(coll, now)))
    (res_dir / "icon.png").write_bytes(_png_illustration(32))
    (docs_dir / "style.css").write_text(STYLE_CSS, "utf-8")
    idx = _index_page(coll, docs, now)
    (docs_dir / "index.html").write_text(idx, "utf-8")

    nbytes = len(idx.encode("utf-8")) + len(STYLE_CSS)
    toc: dict[str, list[tuple[int, str, str]]] = {}
    for n, doc in enumerate(docs, 1):
        page, headings = render_doc_page(doc, resolver, css_href="style.css",
                                         back_href="index.html")
        (docs_dir / f"{doc.doc_id}.html").write_text(page, "utf-8")
        toc[doc.doc_id] = headings
        nbytes += len(page.encode("utf-8"))
        if progress:
            progress(f"docset {n}/{len(docs)} {doc.doc_id}")

    n_entries = _build_dsidx(res_dir / "docSet.dsidx", docs, toc)

    tgz = Path(out_dir) / f"{coll.id}.docset.tgz"
    with tarfile.open(tgz, "w:gz") as tar:
        tar.add(root, arcname=f"{coll.id}.docset")
    return {"id": coll.id, "format": "docset", "path": str(root),
            "docs": len(docs), "bytes": tgz.stat().st_size,
            "entries": n_entries}