"""Shared export layer for third-party reader formats (EPUB / HTML / ZIM / docset).

One RFC .txt -> one clean XHTML chapter:
- page furniture removed (running footers "[Page N]", post-break headers,
  form feeds) while every surviving line keeps its exact whitespace, so
  ASCII diagrams stay pixel-faithful inside <pre>;
- section anchors reuse chunker.find_headings — the same heuristics that
  back the search index — so EPUB nav / docset TOC / deep links agree with
  search results;
- optional linkification of "RFC 9000" style references (internal to the
  exported collection and/or rfc-editor.org) plus bare URLs.

Every exporter (epub.py, htmlexport.py, later zim/docset) shares
iter_export_docs() so collection resolution happens exactly once, the same
way builder.build_pack does.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..index.chunker import find_headings
from .builder import MissingFiles, resolve_files
from .collections import Collection, resolve, sort_key

# Running footer (old format: "Bray ... [Page 1]"; new format: bare
# centered "[Page 7]"); also catches the standalone marker line.
FOOTER_RE = re.compile(r"\[Page \d+\]\s*$")
# Post-page-break header, only dropped when seen right after a break:
# "RFC 8259        JSON        December 2017" / "Internet-Draft ...".
HEADER_RE = re.compile(r"^\s{0,3}(RFC\s+\d+|BCP\s+\d+|STD\s+\d+|FYI\s+\d+|"
                       r"Internet-Draft).{0,60}\s{2,}[A-Z][a-z]+ \d{4}\s*$")
REF_RE = re.compile(r"\b(RFC|BCP|STD|FYI)\s?(\d{1,5})\b")
URL_RE = re.compile(r"https?://[^\s<>\"'()]+")
# Ancient RFCs (RFC 768 etc.) have no modern section structure, and the
# chunker heading heuristics catch their date lines ("28 Aug 1980").
# Harmless in search chunks, noisy in a nav — reject at export time;
# rejected lines just flow back into the <pre> body.
_DATEISH = re.compile(
    r"\d{0,2}\s*(January|February|March|April|May|June|July|August|"
    r"September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|"
    r"Sep|Sept|Oct|Nov|Dec)\s+\d{4}[.,]?\s*\d{0,2}", re.I)

LinkResolver = Callable[[str], Optional[str]]  # "RFC9000" -> href or None


@dataclass
class ExportDoc:
    doc_id: str
    title: str
    status: str
    pub_date: str
    stream: str
    wg: str
    current: bool
    txt_path: Path


def iter_export_docs(conn, coll: Collection, progress=None) -> list[ExportDoc]:
    """Resolve a collection to ExportDocs with local txt files.

    Same pipeline as builder.build_pack: resolve ids, drop content-free
    alias pointers (STD/FYI without files), require local txt (raises
    MissingFiles with sync hint).
    """
    doc_ids = resolve(conn, coll)
    if not doc_ids:
        raise LookupError(f"collection '{coll.id}' resolves to 0 docs")
    doc_ids = [d for d in doc_ids if d.startswith("RFC") or conn.execute(
        "SELECT 1 FROM files WHERE doc_id=? LIMIT 1", (d,)).fetchone()]
    files = resolve_files(conn, doc_ids, ["txt"])
    docs: list[ExportDoc] = []
    for doc_id in sorted((d for d in doc_ids if d in files), key=sort_key):
        row = conn.execute(
            """SELECT title, status, pub_date, is_current, stream, wg
               FROM docs WHERE doc_id=?""", (doc_id,)).fetchone()
        if row is None:
            continue
        docs.append(ExportDoc(
            doc_id=doc_id, title=row["title"] or doc_id,
            status=row["status"] or "", pub_date=row["pub_date"] or "",
            stream=row["stream"] or "", wg=row["wg"] or "",
            current=bool(row["is_current"]), txt_path=files[doc_id]["txt"]))
    if progress:
        progress(f"{len(docs)} docs resolved")
    return docs


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def slug(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.strip()).strip("-").lower()
    return s or "sec"


def _heading_id(num: str, title: str, used: set[str]) -> str:
    if num.startswith("Appendix"):
        base = "app-" + slug(num.split()[-1])
    elif num:
        base = "sec-" + slug(num)
    else:
        base = slug(title)
    hid, n = base, 2
    while hid in used:
        hid, n = f"{base}-{n}", n + 1
    used.add(hid)
    return hid


def _heading_level(num: str) -> int:
    if not num or num.startswith("Appendix"):
        return 2
    parts = num.split(".")
    if parts[0].isalpha():          # "A" / "A.1": letter subsections
        return min(2 + len(parts) - 1, 6)
    return min(2 + len(parts) - 1, 6)


def _esc_refs(text: str, resolver: Optional[LinkResolver]) -> str:
    esc = html.escape(text, quote=False)
    if resolver is None:
        return esc

    def repl(m):
        href = resolver(m.group(1) + m.group(2))
        if not href:
            return m.group(0)
        return (f'<a class="xref" '
                f'href="{html.escape(href, quote=True)}">{m.group(0)}</a>')
    return REF_RE.sub(repl, esc)


def linkify_segment(raw: str, resolver: Optional[LinkResolver]) -> str:
    """Escape a raw text run, linkifying URLs and RFC/BCP/STD/FYI refs."""
    out, pos = [], 0
    for m in URL_RE.finditer(raw):
        out.append(_esc_refs(raw[pos:m.start()], resolver))
        url = m.group(0)
        trail = ""
        while url and url[-1] in ".,;:!?\"'":   # trailing punctuation is prose
            trail = url[-1] + trail
            url = url[:-1]
        out.append(f'<a class="url" href="{html.escape(url, quote=True)}">'
                   f'{html.escape(url)}</a>')
        out.append(_esc_refs(trail, resolver))
        pos = m.end()
    out.append(_esc_refs(raw[pos:], resolver))
    return "".join(out)


def render_body(doc: ExportDoc,
                resolver: Optional[LinkResolver] = None,
                ) -> tuple[str, list[tuple[int, str, str]]]:
    """Render the txt body to XHTML.

    Returns (body_html, headings) where headings are (level, id, text)
    in document order — exporters reuse them for nav/TOC/search indexes.
    """
    lines = _decode(doc.txt_path).lstrip("\ufeff").splitlines()
    heads = [(i, num, title) for i, num, title in find_headings(lines)
             if not _DATEISH.fullmatch(lines[i].strip())]
    hmap = {i: (num, title) for i, num, title in heads}
    toc_ranges = set()
    for k, (i, _num, title) in enumerate(heads):
        if title == "Table of Contents":  # real nav replaces the dot-leader ToC
            nxt = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            toc_ranges.update(range(i + 1, nxt))

    parts: list[str] = []
    buf: list[str] = []
    headings: list[tuple[int, str, str]] = []
    used: set[str] = set()

    def flush():
        while buf and not buf[-1].strip():
            buf.pop()
        if buf and any(ln.strip() for ln in buf):
            parts.append("<pre>" + linkify_segment("\n".join(buf), resolver)
                         + "</pre>")
        buf.clear()

    after_break = False
    for i, raw in enumerate(lines):
        if i in hmap:
            flush()
            num, title = hmap[i]
            if title == "Table of Contents":
                hid = _heading_id("toc", "toc", used)
            else:
                hid = _heading_id(num, title, used)
            level = _heading_level(num)
            text = re.sub(r"\s{2,}", " ", lines[i].strip())
            parts.append(f'<h{level} id="{hid}">{html.escape(text)}</h{level}>')
            headings.append((level, hid, text))
            after_break = False
            continue
        if i in toc_ranges:
            continue
        was_break = "\f" in raw or bool(FOOTER_RE.search(raw))
        if was_break:
            raw = raw.replace("\f", "")
            if not raw.strip():
                after_break = True
                continue
        if after_break and HEADER_RE.match(raw):
            after_break = False
            continue
        after_break = False
        buf.append(raw.rstrip())
    flush()
    return "\n".join(parts), headings


def render_doc_page(doc: ExportDoc, resolver: Optional[LinkResolver] = None,
                    css_href: str = "../style.css",
                    back_href: Optional[str] = None,
                    ) -> tuple[str, list[tuple[int, str, str]]]:
    """Full standalone page for one document; also returns its headings."""
    body, headings = render_body(doc, resolver)
    meta_bits = [b for b in (
        doc.status,
        f"published {doc.pub_date}" if doc.pub_date else "",
        doc.stream, doc.wg,
        "current" if doc.current else "obsolete") if b]
    back = (f'<p class="back"><a href="{html.escape(back_href, quote=True)}">'
            f'index</a></p>\n' if back_href else "")
    page = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
<meta charset="utf-8"/>
<title>{html.escape(f'{doc.doc_id}: {doc.title}')}</title>
<link rel="stylesheet" type="text/css" href="{html.escape(css_href, quote=True)}"/>
</head>
<body>
{back}<header class="doc-head">
<h1>{html.escape(doc.doc_id)}: {html.escape(doc.title)}</h1>
<p class="meta">{html.escape(" · ".join(meta_bits))}</p>
</header>
{body}
</body>
</html>
"""
    return page, headings


def make_resolver(known_files: dict[str, str], mode: str) -> Optional[LinkResolver]:
    """Build the reference resolver for 'none|internal|external' modes."""
    if mode == "none":
        return None

    def resolve_ref(ref: str) -> Optional[str]:
        if ref in known_files:
            return known_files[ref]
        if mode == "external" and ref.startswith("RFC"):
            return "https://www.rfc-editor.org/rfc/" + ref.lower()
        if mode == "external":            # BCP/STD/FYI info pages
            return "https://www.rfc-editor.org/info/" + ref.lower()
        return None
    return resolve_ref


STYLE_CSS = """\
body { font-family: Georgia, 'Times New Roman', serif; margin: 1.5em auto;
       max-width: 72ch; padding: 0 1em; line-height: 1.5; color: #1b1f23; }
h1 { font-size: 1.45em; }
h2 { font-size: 1.25em; margin-top: 1.6em; border-bottom: 1px solid #d0d7de;
     padding-bottom: .2em; }
h3, h4, h5, h6 { font-size: 1.08em; margin-top: 1.3em; }
pre { font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
      font-size: .82em; background: #f6f8fa; border: 1px solid #d0d7de;
      border-radius: 6px; padding: .8em; overflow-x: auto;
      white-space: pre; tab-size: 4; }
code, kbd { font-family: inherit; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
.meta, .back { color: #57606a; font-size: .9em; font-family: sans-serif; }
table.index { border-collapse: collapse; width: 100%; font-size: .95em; }
table.index th, table.index td { border-bottom: 1px solid #d0d7de;
       padding: .35em .6em; text-align: left; vertical-align: top; }
table.index td.num { white-space: nowrap; font-family: monospace; }
@media (prefers-color-scheme: dark) {
  body { color: #e6edf3; background: #0d1117; }
  pre, table.index th, table.index td { border-color: #30363d; }
  pre { background: #161b22; }
  h2 { border-color: #30363d; }
  .meta, .back { color: #8b949e; }
  a { color: #4493f8; }
}
"""

__all__ = ["ExportDoc", "MissingFiles", "STYLE_CSS", "iter_export_docs",
           "linkify_segment", "make_resolver", "render_body",
           "render_doc_page", "slug"]

