"""The search index of the imported POSIX edition, on the core FTS5 index (`primarysource.index`).

One core document per page (`functions/open`), one core section per heading, keyed by the heading's anchor, so a
hit is a ref `posix-2024§functions/open#tag_17_372_03` that `posix.read` accepts. A section's indexed body is the
blocks it owns, those between its heading and the next heading of any level, so a parent is not credited with its
subsections' text. The text before the first heading is the section `""`, whose hit is the page itself.

The index is one file beside the edition, `<home>/posix/<edition>.sqlite` (the edition directory itself is replaced
whole by a re-import, so it cannot hold the index). It is rebuilt atomically by `build`, which runs at the end of
`primarysource posix import` and as `primarysource posix index`.

**Staleness.** The sha256 of the edition's `install.json` is a sentinel document (`SOURCE_ID`, title = digest, no
sections, never a hit), written in the same atomic rebuild. A re-import changes the record, so an index built from
the earlier import is refused with the command that rebuilds it.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from primarysource import index
from primarysource.errors import LibError
from primarysource.ieee import POSIX
from primarysource.ieee.catalogue import POSIX_2024, Edition
from primarysource.ieee.importer import INSTALL_RECORD, collection_home
from primarysource.ieee.posix import VOLUMES, _plain, _ref_text, installed, load_page, pages
from primarysource.model import Document, Section, Unit
from primarysource.render import next_start, render

SOURCE_ID = "#source"
INDEX_COMMAND = "primarysource posix index"
MAX_QUERY = 500
MAX_HITS = 50

# A heading counts four times a body word, as in the other collections; the page title (every section of a page
# carries it) counts once.
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)


def index_path(edition: Edition = POSIX_2024, home: Path | None = None) -> Path:
    return collection_home("posix", home) / f"{edition.id}.sqlite"


def _digest(root: Path) -> str:
    return hashlib.sha256((root / INSTALL_RECORD).read_bytes()).hexdigest()


def _documents(edition: Edition, home: Path | None) -> Iterator[Document]:
    for page in pages(edition=edition, home=home):
        loaded = load_page(page, edition=edition, home=home)
        converted = loaded.converted
        title = loaded.document.title
        volume = VOLUMES.get(page.split("/")[0], "")
        heads = converted.headings
        sections: list[Section] = []
        first = heads[0].block if heads else len(converted.blocks)
        if first:
            sections.append(Section("", title, ("\n\n".join(_plain(b) for b in converted.blocks[:first]),), 0))
        for position, head in enumerate(heads):
            end = heads[position + 1].block if position + 1 < len(heads) else len(converted.blocks)
            owned = "\n\n".join(_plain(b) for b in converted.blocks[head.block + 1 : end])
            sections.append(Section(head.anchor or f"_{position + 1}", head.text, (owned,), head.level))
        yield Document(page, f"{volume} {title}".strip(), Unit.BLOCK, tuple(sections))


def build(*, edition: Edition = POSIX_2024, home: Path | None = None) -> int:
    """Rebuild the index from the imported pages; returns the number of sections indexed."""
    root = installed(edition, home)
    digest = _digest(root)

    def everything() -> Iterator[Document]:
        yield from _documents(edition, home)
        yield Document(SOURCE_ID, digest, Unit.BLOCK)

    return index.rebuild(index_path(edition, home), everything(), rebuild_command=INDEX_COMMAND)


def open_index(*, edition: Edition = POSIX_2024, home: Path | None = None) -> sqlite3.Connection:
    """A read-only connection to the index, or a LibError naming `primarysource posix index`."""
    root = installed(edition, home)
    path = index_path(edition, home)
    if not path.is_file():
        raise LibError(f"no search index for {edition.id}: it has not been indexed", "", INDEX_COMMAND)
    try:
        conn = index.open_read(path, rebuild_command=INDEX_COMMAND)
    except LibError as error:
        raise LibError(error.message, "", INDEX_COMMAND) from None
    try:
        row = conn.execute("SELECT title FROM documents WHERE doc_id = ?", (SOURCE_ID,)).fetchone()
    except sqlite3.DatabaseError as error:
        conn.close()
        raise LibError(f"{path} is not a readable search index: {error}", "", INDEX_COMMAND) from None
    if row is None or row[0] != _digest(root):
        conn.close()
        raise LibError(
            f"the search index at {path} is stale: {edition.id} was imported again since it was built",
            "",
            INDEX_COMMAND,
        )
    return conn


_NON_WORD = re.compile(r"\W+")


def _stems(query: str) -> list[str]:
    """Crude prefixes of the query's terms, to find which block of a hit's section a `¶n` should name."""
    out = []
    for term in index.query_terms(query):
        word = _NON_WORD.sub("", term).casefold()
        if word:
            out.append(word[: max(3, len(word) - 3)])
    return out


def _para(page: str, anchor: str, stems: list[str], edition: Edition, home: Path | None) -> int | None:
    """The 1-based block, within the section, that holds the most of the query's terms (None if only the
    heading matched)."""
    loaded = load_page(page, edition=edition, home=home)
    section = loaded.document.section(anchor) if anchor else None
    blocks = section.units if section is not None else tuple(loaded.converted.blocks)
    best, best_count = None, 0
    for number, block in enumerate(blocks, start=1):
        text = _plain(block).casefold()
        count = sum(1 for s in stems if s in text)
        if count > best_count:
            best, best_count = number, count
    return best


def search(
    query: str,
    *,
    limit: int = 8,
    start: int = 0,
    edition: Edition = POSIX_2024,
    home: Path | None = None,
) -> str:
    """The best sections for `query`, best first, `limit` from the 0-based `start`: one `<ref>  <title>` line per
    hit with a snippet under it. `next: start=<n>` continues. No hits means nothing matched."""
    if not index.query_terms(query) or len(query) > MAX_QUERY:
        raise LibError(
            f"search needs between 1 and {MAX_QUERY} characters with at least one word",
            "for example posix_search('sprocket gasket')",
        )
    if limit < 1:
        raise LibError("limit must be at least 1", "")
    if start < 0:
        raise LibError(f"start is a 0-based offset, not {start}", "pass the start= value of the last next: line")
    limit = min(limit, MAX_HITS)
    conn = open_index(edition=edition, home=home)
    try:
        result = index.search(conn, query, ranking=RANKING, limit=limit, start=start)
    finally:
        conn.close()
    if not result.hits:
        body = f"no more sections for {query!r} after {start}" if start else f"nothing matches {query!r}"
        return render(body, {"unit": POSIX.unit})
    stems = _stems(query)
    lines = [f"Sections {start + 1}-{start + len(result.hits)} for {query!r}, best first:"]
    for hit in result.hits:
        para = _para(hit.doc_id, hit.section_id, stems, edition, home)
        ref = _ref_text(edition.id, hit.doc_id, hit.section_id, para)
        snippet = " ".join(hit.snippet.split())
        lines.append(f"\n{ref}  {hit.doc_title}: {hit.title}  (score {hit.score:.3g})\n  {snippet}")
    footer = {
        "unit": POSIX.unit,
        "next": next_start(result.next_start),
        "relaxed": "no section holds every query word; these hold some" if result.relaxed else "",
    }
    return render("\n".join(lines), footer)
