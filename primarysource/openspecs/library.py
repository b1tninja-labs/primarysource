"""Read, outline, search and cite the stored Open Specifications pages. Local files only; nothing here fetches.

A ref is `openspecs:MS-SMB2§2.2.1¶2`. The `openspecs:` prefix is optional and the document id is case-insensitive.
`§` is the section id from the Learn table of contents (a section number such as `2.2.1`, or a slug when the
title has none). `¶n` is the nth block of that page. A ref with no section is not a read of the whole
specification: the outline names the section to pass.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from primarysource import budget, cursor
from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.index import Hit, Ranking, SearchResult, fts_query, open_read, rebuild
from primarysource.model import span_hash
from primarysource.openspecs.site import DOC_ID, SECTION_ID
from primarysource.openspecs.sync import (
    INDEX,
    REBUILD,
    Page,
    document_from,
    load_catalog,
    page_file,
)
from primarysource.refs import Ref, RefGrammar
from primarysource.render import render

PREFIX = "openspecs:"
SYNC = "primarysource openspecs sync"
_DOC = re.compile(r"\s*((?:MS|MC|TN)-[A-Za-z0-9]+)", re.IGNORECASE)


def grammar() -> RefGrammar:
    return RefGrammar(DOC_ID.pattern, SECTION_ID.pattern)


def default_home() -> Path:
    return collection_home("openspecs")


def parse_ref(text: str) -> Ref:
    """`openspecs:MS-SMB2§2.2.1¶2`, with the prefix optional and the document id in either case."""
    raw = text.strip()
    if raw.casefold().startswith(PREFIX):
        raw = raw[len(PREFIX) :]
    match = _DOC.match(raw)
    if match:
        raw = match.group(1).upper() + raw[match.end() :]
    return grammar().parse(raw)


def docs(home: Path | None = None, *, start: int = 0, limit: int = 50) -> str:
    """One line per specification: id, how many pages are catalogued, how many are stored, the title."""
    home = home or default_home()
    pages = load_catalog(home)
    counts: dict[str, list[int]] = {}
    for page in pages:
        counts.setdefault(page.doc, [0, 0])
        counts[page.doc][0] += 1
        if page_file(home, page.doc, page.section).is_file():
            counts[page.doc][1] += 1
    titles = _titles(home)
    rows = [
        f"{doc}  {stored}/{total} pages  {titles.get(doc, '')}".rstrip()
        for doc, (total, stored) in sorted(counts.items())
    ]
    window, nxt = cursor.window(rows, start, limit)
    return render("\n".join(window), {"next": nxt})


def outline(doc: str, home: Path | None = None) -> str:
    """A specification's pages, indented by the table-of-contents depth, each with the ref that reads it."""
    home = home or default_home()
    spec = _doc(doc)
    pages = [page for page in load_catalog(home) if page.doc == spec]
    if not pages:
        raise LibError(f"no specification {spec}", "primarysource openspecs docs")
    lines = []
    for page in pages:
        stored = page_file(home, page.doc, page.section).is_file()
        mark = "" if stored else " (not downloaded)"
        indent = "  " * max(page.depth - 1, 0)
        lines.append(f"{indent}{page.section}  {page.title}  {_ref(page)}{mark}")
    return render("\n".join(lines), {})


def read(ref: str, home: Path | None = None, *, max_tokens: int = 2000) -> str:
    """One page, cut at block boundaries. `next:` is the ref that reads the following blocks."""
    home = home or default_home()
    parsed = parse_ref(ref)
    if not parsed.doc or not parsed.section:
        raise LibError(f"not a page ref: {ref!r}", "a ref names a document and a section, as in MS-SMB2§2.2.1")
    page = _page(home, parsed.doc, parsed.section)
    blocks = _blocks(home, page)
    if not blocks:
        raise LibError(f"{_ref(page)} has no text", SYNC)
    start = cursor.first_unit(parsed.para, len(blocks), "blocks", _ref(page))
    shown = budget.page(blocks, start, max_tokens)
    body = "\n\n".join(shown.units)
    cite = _ref(page) if shown.first == 1 and parsed.para is None else f"{_ref(page)}¶{shown.first}"
    if shown.last > shown.first:
        cite = f"{_ref(page)}¶{shown.first}-{shown.last}"
    nxt = cursor.read_next(_ref(page), shown)
    return render(body, {"cite": cite, "unit": "block", "next": nxt})


def search(query: str, home: Path | None = None, *, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Sections whose text contains the query words. Every word is required first; otherwise any word, flagged
    relaxed."""
    home = home or default_home()
    spec = _doc(doc) if doc else None
    path = home / INDEX
    conn = open_read(path, rebuild_command=REBUILD)
    try:
        if conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0:
            raise LibError("the Open Specifications index is empty", action=SYNC)
        found = _search(conn, query, spec, limit, start)
    finally:
        conn.close()
    lines = [f"{PREFIX}{hit.doc_id}§{hit.section_id}: {hit.snippet.replace(chr(10), ' ')}" for hit in found.hits]
    footer = {"next": f"start={found.next_start}" if found.next_start is not None else "", "relaxed": ""}
    if found.relaxed:
        footer["relaxed"] = "true"
    return render("\n".join(lines), footer)


def cite(ref: str, home: Path | None = None) -> str:
    """The citation for one block, and the sha256 prefix of that exact text."""
    home = home or default_home()
    parsed = parse_ref(ref)
    if not parsed.doc or not parsed.section or parsed.para is None:
        raise LibError(f"cite names one block: {ref!r}", "use a ref such as MS-SMB2§2.2.1¶1")
    page = _page(home, parsed.doc, parsed.section)
    blocks = _blocks(home, page)
    if parsed.para > len(blocks):
        raise LibError(f"{_ref(page)} has {len(blocks)} blocks", f"use ¶1 to ¶{len(blocks)}" if blocks else "")
    text = blocks[parsed.para - 1]
    named = f"{_ref(page)}¶{parsed.para}"
    return render(text, {"cite": named, "unit": "block", "span": span_hash(text)})


def build_index(home: Path | None = None) -> int:
    """Rebuild the search index from the pages already stored. Nothing is downloaded."""
    home = home or default_home()
    pages = load_catalog(home)
    titles = _titles(home)
    grouped: dict[str, list[Page]] = {}
    for page in pages:
        grouped.setdefault(page.doc, []).append(page)
    documents = [
        document_from(home, spec, titles.get(spec, spec), spec_pages)
        for spec, spec_pages in grouped.items()
        if any(page_file(home, page.doc, page.section).is_file() for page in spec_pages)
    ]
    return rebuild(home / INDEX, documents, rebuild_command=REBUILD)


def _search(conn: sqlite3.Connection, query: str, doc: str | None, limit: int, start: int) -> SearchResult:
    """`index.search`, plus a document filter the shared search does not take."""
    if limit < 1 or start < 0:
        raise LibError("limit must be at least 1 and start at least 0", "start is the start= value of a next: line")
    ranking = Ranking()
    fetch = start + limit + ranking.candidates
    strict = fts_query(query)
    hits = _match(conn, strict, doc, ranking, fetch)
    relaxed = False
    if not hits:
        loose = fts_query(query, any_term=True)
        if loose != strict:
            hits = _match(conn, loose, doc, ranking, fetch)
            relaxed = bool(hits)
    page = tuple(hits[start : start + limit])
    more = len(hits) > start + limit
    return SearchResult(page, relaxed, start + len(page) if more else None)


def _match(conn: sqlite3.Connection, expression: str, doc: str | None, ranking: Ranking, fetch: int) -> list[Hit]:
    order = ranking.bm25()
    where = "sections_fts MATCH ?"
    params: list[object] = [expression]
    if doc is not None:
        where += " AND s.doc_id = ?"
        params.append(doc)
    params.append(fetch)
    rows = conn.execute(
        "SELECT s.doc_id, s.section_id, s.doc_title, s.title, "  # noqa: S608 - only the constant bm25 weights
        f"snippet(sections_fts, 2, '', '', ' … ', 24), {order} "
        f"FROM sections_fts JOIN sections AS s ON s.id = sections_fts.rowid WHERE {where} "
        f"ORDER BY {order}, s.id LIMIT ?",
        params,
    ).fetchall()
    return [Hit(row[0], row[1], row[2], row[3], row[4] or row[3], -row[5]) for row in rows]


def _page(home: Path, doc: str, section: str) -> Page:
    for page in load_catalog(home):
        if page.doc == doc and page.section == section:
            return page
    raise LibError(f"no page {doc}§{section}", "primarysource openspecs outline " + doc)


def _blocks(home: Path, page: Page) -> tuple[str, ...]:
    path = page_file(home, page.doc, page.section)
    if not path.is_file():
        raise LibError(f"{_ref(page)} is catalogued but not downloaded", action=f"{SYNC} --only {page.doc}")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(f"{path} is not a stored page", action=f"{SYNC} --only {page.doc}") from exc
    blocks = stored.get("blocks") if isinstance(stored, dict) else None
    if not isinstance(blocks, list):
        raise LibError(f"{path} is not a stored page", action=f"{SYNC} --only {page.doc}")
    return tuple(block for block in blocks if isinstance(block, str))


def _titles(home: Path) -> dict[str, str]:
    path = home / "catalog.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _doc(token: str) -> str:
    text = token.strip()
    if text.casefold().startswith(PREFIX):
        text = text[len(PREFIX) :]
    text = text.split("§", 1)[0].upper()
    if DOC_ID.fullmatch(text) is None:
        raise LibError(f"not an Open Specifications id: {token!r}", "use an id such as MS-SMB2")
    return text


def _ref(page: Page) -> str:
    return f"{PREFIX}{page.doc}§{page.section}"
