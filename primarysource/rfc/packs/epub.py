"""EPUB 3 export: one collection -> one .epub (pure stdlib).

EPUB is an OCF zip: uncompressed `mimetype` first, container.xml pointing
at package.opf, EPUB3 nav.xhtml for the table of contents. Chapters are
the same XHTML pages the HTML export produces, so an RFC's ASCII diagrams
and section anchors survive intact; search is the reader's job (ReadEra,
Apple Books, Play Books all index chapter text). No NCX: EPUB3 readers
use the nav document.
"""

from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xesc

from .collections import Collection
from .export import (ExportDoc, STYLE_CSS, make_resolver, render_doc_page,
                     slug)

MIMETYPE = "application/epub+zip"
_NAV_MAX_SECTIONS = 150   # nested entries per document chapter


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _opf(coll: Collection, entries: list[tuple[str, str, str]],
         spine: list[str], now: str) -> str:
    """entries: (id, href, title); spine: manifest ids in reading order."""
    ident = "urn:uuid:" + hashlib.sha1(
        ("rfclib:" + coll.id).encode()).hexdigest()[:32]
    manifest = "\n".join(
        f'    <item id="{i}" href="{xesc(h)}" '
        f'media-type="application/xhtml+xml"/>' for i, h, _t in entries)
    manifest += ('\n    <item id="title" href="title.xhtml" '
                 'media-type="application/xhtml+xml"/>'
                 '\n    <item id="nav" href="nav.xhtml" '
                 'media-type="application/xhtml+xml" properties="nav"/>'
                 '\n    <item id="css" href="style.css" media-type="text/css"/>')
    sp = "\n".join(f'    <itemref idref="{i}"/>'
                   for i in ["title"] + spine + ["nav"])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bid">{ident}</dc:identifier>
    <dc:title>{xesc(coll.name)}</dc:title>
    <dc:language>en</dc:language>
    <dc:creator>rfclib</dc:creator>
    <dc:publisher>rfclib</dc:publisher>
    <dc:date>{now[:10]}</dc:date>
    <meta property="dcterms:modified">{now}</meta>
  </metadata>
  <manifest>
{manifest}
  </manifest>
  <spine>
{sp}
  </spine>
</package>
"""


def _nav(title_href: str, chapters: list[tuple[str, str, list]]) -> str:
    """chapters: (href, doc label, [(level, id, text), ...])."""
    items = []
    for href, label, heads in chapters:
        nested = ""
        shown = [h for h in heads if h[0] <= 3][:_NAV_MAX_SECTIONS]
        if shown:
            inner = "".join(
                f'<li><a href="{xesc(href)}#{i}">{xesc(t)}</a></li>'
                for _lvl, i, t in shown)
            nested = f"<ol>{inner}</ol>"
        items.append(f'<li><a href="{xesc(href)}">{xesc(label)}</a>{nested}</li>')
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
<head><meta charset="utf-8"/><title>Table of Contents</title></head>
<body>
<nav epub:type="toc">
<h1>Table of Contents</h1>
<ol>
<li><a href="{xesc(title_href)}">Cover</a></li>
{"".join(items)}
</ol>
</nav>
</body>
</html>
"""


def _cover(coll: Collection, docs: list[ExportDoc], now: str) -> str:
    rows = "".join(
        f'<tr><td><a href="text/{d.doc_id}.xhtml">{d.doc_id}</a></td>'
        f"<td>{xesc(d.title)}</td></tr>" for d in docs)
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head><meta charset="utf-8"/><title>{xesc(coll.name)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<h1>{xesc(coll.name)}</h1>
<p class="meta">{len(docs)} documents · generated {now} · rfclib export</p>
<p>{xesc(coll.description)}</p>
<table class="index">
<tr><th>Doc</th><th>Title</th></tr>
{rows}
</table>
</body>
</html>
"""


def build_epub(coll: Collection, docs: list[ExportDoc], out_path: Path,
               link_refs: str = "internal", progress=None) -> dict:
    """Write <out_path>/<coll.id>.epub; returns a summary dict."""
    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)
    known = {d.doc_id: f"text/{d.doc_id}.xhtml" for d in docs}
    resolver = make_resolver(known, link_refs)
    now = _now()

    chapters: list[tuple[str, str, list]] = []
    pages: list[tuple[str, str]] = []          # (arcname, content)
    for n, doc in enumerate(docs, 1):
        page, heads = render_doc_page(doc, resolver, css_href="../style.css")
        arc = f"OEBPS/text/{doc.doc_id}.xhtml"
        pages.append((arc, page))
        chapters.append((f"text/{doc.doc_id}.xhtml",
                         f"{doc.doc_id}: {doc.title}", heads))
        if progress:
            progress(f"epub {n}/{len(docs)} {doc.doc_id}")

    entries = [(f"doc-{slug(d.doc_id)}", f"text/{d.doc_id}.xhtml", d.title)
               for d in docs]
    spine = [i for i, _h, _t in entries]
    tmp = out_path / (coll.id + ".epub.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        mi = zipfile.ZipInfo("mimetype", date_time=(1980, 1, 1, 0, 0, 0))
        zf.writestr(mi, MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/package.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""")
        zf.writestr("OEBPS/package.opf", _opf(coll, entries, spine, now))
        zf.writestr("OEBPS/nav.xhtml", _nav("title.xhtml", chapters))
        zf.writestr("OEBPS/title.xhtml", _cover(coll, docs, now))
        zf.writestr("OEBPS/style.css", STYLE_CSS)
        for arc, content in pages:
            zf.writestr(arc, content)
    final = out_path / (coll.id + ".epub")
    tmp.replace(final)
    return {"id": coll.id, "format": "epub", "path": str(final),
            "docs": len(docs), "bytes": final.stat().st_size}
