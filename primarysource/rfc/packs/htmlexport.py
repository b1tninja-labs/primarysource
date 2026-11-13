"""Static HTML mirror export: one collection -> a browsable folder tree.

<out>/<coll.id>/
  index.html      sortable-in-browser table of all docs
  style.css
  text/RFC9000.html  one page per doc, section anchors, cross links

The point: grep/Everything/Windows-Search friendly, opens in any browser,
forever — the workflow CHM used to own on Windows without CHM's dead
tooling. Same page renderer as the EPUB export (export.py), so both stay
in lockstep.
"""

from __future__ import annotations

import html as htmllib
from datetime import datetime, timezone
from pathlib import Path

from .collections import Collection
from .export import ExportDoc, STYLE_CSS, make_resolver, render_doc_page


def _index_page(coll: Collection, docs: list[ExportDoc], now: str) -> str:
    rows = []
    for d in docs:
        rows.append(
            "<tr>"
            f'<td class="num"><a href="text/{htmllib.escape(d.doc_id)}.html">'
            f"{htmllib.escape(d.doc_id)}</a></td>"
            f"<td>{htmllib.escape(d.title)}</td>"
            f"<td>{htmllib.escape(d.status)}</td>"
            f'<td class="num">{htmllib.escape(d.pub_date)}</td>'
            f"<td>{'current' if d.current else 'obsolete'}</td>"
            "</tr>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{htmllib.escape(coll.name)} — rfclib export</title>
<link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
<h1>{htmllib.escape(coll.name)}</h1>
<p class="meta">{len(docs)} documents · generated {now} · rfclib HTML mirror
(offline; searchable via browser find / grep / Everything)</p>
<p>{htmllib.escape(coll.description)}</p>
<table class="index">
<tr><th>Doc</th><th>Title</th><th>Status</th><th>Published</th><th></th></tr>
{"".join(rows)}
</table>
</body>
</html>
"""


def build_html(coll: Collection, docs: list[ExportDoc], out_dir: Path,
               link_refs: str = "internal", progress=None) -> dict:
    """Write <out_dir>/<coll.id>/ HTML mirror; returns a summary dict."""
    root = Path(out_dir) / coll.id
    text_dir = root / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    known = {d.doc_id: f"{d.doc_id}.html" for d in docs}
    resolver = make_resolver(known, link_refs)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    nbytes = 0
    (root / "style.css").write_text(STYLE_CSS, "utf-8")
    for n, doc in enumerate(docs, 1):
        page, _heads = render_doc_page(doc, resolver, css_href="../style.css",
                                       back_href="../index.html")
        p = text_dir / f"{doc.doc_id}.html"
        p.write_text(page, "utf-8")
        nbytes += len(page.encode("utf-8"))
        if progress:
            progress(f"html {n}/{len(docs)} {doc.doc_id}")
    idx = _index_page(coll, docs, now)
    (root / "index.html").write_text(idx, "utf-8")
    nbytes += len(idx.encode("utf-8")) + len(STYLE_CSS)
    return {"id": coll.id, "format": "html", "path": str(root),
            "docs": len(docs), "bytes": nbytes}
