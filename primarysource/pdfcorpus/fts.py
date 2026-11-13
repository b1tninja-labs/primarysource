"""The search index of a fetched-document collection: its sections in the core FTS5 index (`primarysource.index`).

`build` writes `<corpus>/sections.sqlite` from `index.json` and the extracted text, atomically, when the corpus is
fetched or when `primarysource <collection> index` is run. `open_index` opens it read-only (`mode=ro`) for search,
so the server never re-reads or re-tokenises the text to answer a query.

A section's indexed body is the text it owns: the lines in its range that no narrower section claims, so a parent
section is not credited with its children's text (the rule the old in-memory scan had).

**Staleness.** The index records the sha256 of the `index.json` it was built from, as a sentinel row in the core
`documents` table (`SOURCE_ID`, title = the digest, no sections, so it is never a search hit). It is written in the
same atomic rebuild as the sections. An index whose digest differs from the loaded corpus is refused with a
`CorpusError` whose `action` is the index command, as is a missing one. (The core index has no metadata table;
when it grows one, the digest moves there.)
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from primarysource import index
from primarysource.errors import LibError
from primarysource.model import Document as IndexedDocument
from primarysource.model import Section as IndexedSection
from primarysource.model import Unit
from primarysource.pdfcorpus.corpus import Corpus, CorpusError, load_corpus
from primarysource.pdfcorpus.models import Document

if TYPE_CHECKING:
    from primarysource.pdfcorpus.spec import CorpusSpec

INDEX_FILE = "sections.sqlite"
SOURCE_ID = "#source"

# The old scan scored a heading word 3 above a body word, plus 5 per distinct word: heading hits weigh more. As
# BM25 column weights: the section heading counts four times the body, the document's number and title once.
RANKING = index.Ranking(doc_title=1.0, title=4.0, body=1.0)


def index_path(root: Path) -> Path:
    return root / INDEX_FILE


def owned_lines(document: Document, line_count: int) -> dict[str, list[int]]:
    """Section id -> the 1-based line numbers it owns: a line belongs to the narrowest section containing it."""
    owner: dict[int, str] = {}
    for section in sorted(document.sections, key=lambda s: s.end_line - s.start_line, reverse=True):
        for number in range(section.start_line, min(section.end_line, line_count) + 1):
            owner[number] = section.id
    owned: dict[str, list[int]] = {section.id: [] for section in document.sections}
    for number in sorted(owner):
        owned[owner[number]].append(number)
    return owned


def indexed_document(corpus: Corpus, document: Document) -> IndexedDocument:
    """One corpus document as the core index stores it: one unit per section, the text the section owns."""
    lines = corpus.text_lines(document)
    owned = owned_lines(document, len(lines))
    return IndexedDocument(
        id=document.doc_id,
        title=f"{document.number} {document.title}",
        unit=Unit.BLOCK,
        sections=tuple(
            IndexedSection(
                id=section.id,
                title=section.heading,
                units=("\n".join(lines[n - 1] for n in owned[section.id]),),
                depth=section.id.count(".") + 1,
            )
            for section in document.sections
        ),
    )


def build(corpus: Corpus) -> int:
    """Rebuild `<corpus>/sections.sqlite` from the loaded corpus; returns the number of sections indexed."""
    documents = [indexed_document(corpus, document) for document in corpus.documents]
    documents.append(IndexedDocument(id=SOURCE_ID, title=corpus.digest, unit=Unit.BLOCK))
    return index.rebuild(index_path(corpus.root), documents, rebuild_command=corpus.index_command)


def open_index(corpus: Corpus) -> sqlite3.Connection:
    """A read-only connection to the corpus's search index, or a `CorpusError` naming the index command."""
    path = index_path(corpus.root)
    action = corpus.index_command
    if not path.is_file():
        raise CorpusError(f"no search index at {path}: the corpus has not been indexed", action=action)
    try:
        conn = index.open_read(path, rebuild_command=action)
    except LibError as error:
        raise CorpusError(error.message, action=action) from None
    try:
        row = conn.execute("SELECT title FROM documents WHERE doc_id = ?", (SOURCE_ID,)).fetchone()
    except sqlite3.DatabaseError as error:
        conn.close()
        raise CorpusError(f"{path} is not a readable search index: {error}", action=action) from None
    if row is None or row[0] != corpus.digest:
        conn.close()
        stale = f"the search index at {path} is stale: index.json changed since it was built"
        raise CorpusError(stale, action=action)
    return conn


def _match_in(
    conn: sqlite3.Connection, expression: str, doc_id: str, ranking: index.Ranking, fetch: int
) -> list[index.Hit]:
    order = ranking.bm25()
    rows = conn.execute(
        "SELECT s.doc_id, s.section_id, s.doc_title, s.title, "  # noqa: S608 - only formatted floats are interpolated
        f"snippet(sections_fts, 2, '', '', ' … ', 24), {order} "
        "FROM sections_fts JOIN sections AS s ON s.id = sections_fts.rowid "
        f"WHERE sections_fts MATCH ? AND s.doc_id = ? ORDER BY {order}, s.id LIMIT ?",
        (expression, doc_id, fetch),
    ).fetchall()
    return [index.Hit(row[0], row[1], row[2], row[3], row[4] or row[3], -row[5]) for row in rows]


def search(
    conn: sqlite3.Connection, query: str, *, doc_id: str | None = None, limit: int = 8, start: int = 0
) -> index.SearchResult:
    """`index.search` with this collection's ranking, optionally within one document.

    The core search has no document filter yet, so a restricted search runs the same strict-then-relaxed query
    here with `s.doc_id = ?` added: the decision to relax is then taken within the document, not across the corpus.
    """
    if doc_id is None:
        return index.search(conn, query, ranking=RANKING, limit=limit, start=start)
    fetch = start + limit + 1
    strict = index.fts_query(query)
    hits = _match_in(conn, strict, doc_id, RANKING, fetch)
    relaxed = False
    if not hits:
        loose = index.fts_query(query, any_term=True)
        if loose != strict:
            hits = _match_in(conn, loose, doc_id, RANKING, fetch)
            relaxed = bool(hits)
    page = tuple(hits[start : start + limit])
    more = len(hits) > start + limit
    return index.SearchResult(page, relaxed, start + len(page) if more else None)


def main(spec: CorpusSpec, argv: Sequence[str]) -> int:
    """`primarysource <collection> index [--corpus DIR]`: rebuild the search index from the fetched corpus."""
    parser = argparse.ArgumentParser(
        prog=spec.index_command or f"primarysource {spec.name} index",
        description="Rebuild the search index from the fetched corpus (index.json and the extracted text).",
    )
    parser.add_argument("--corpus", type=Path, default=None, help=f"corpus directory (default: ${spec.env_var})")
    args = parser.parse_args(list(argv))
    try:
        corpus = load_corpus(spec, args.corpus)
        written = build(corpus)
    except LibError as error:
        print(error.as_text(), file=sys.stderr)
        return 2
    print(f"indexed {written} section(s) of {len(corpus.documents)} document(s) into {index_path(corpus.root)}")
    return 0


def build_after_fetch(spec: CorpusSpec, root: Path) -> bool:
    """Called by a fetch once `index.json` is written: rebuild the search index, report, and say if it worked."""
    try:
        corpus = load_corpus(spec, root)
        written = build(corpus)
    except LibError as error:
        print(f"search index not rebuilt:\n{error.as_text()}", file=sys.stderr)
        return False
    print(f"indexed {written} section(s) into {index_path(root)}")
    return True
