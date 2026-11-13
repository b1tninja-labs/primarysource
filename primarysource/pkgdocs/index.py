"""A per-edition full-text index: SQLite FTS5, built once at import, opened read-only.

One row per section (its title and its blocks), ranked by BM25 with the title weighted over the body. This is the
interim form of the core's `cl.index_fts5`; it keeps the rules the roadmap already names for that row (a sanitiser
that quotes user text term by term so FTS5 operators cannot raise, strict AND then a relaxed OR that says so, a
file that is built beside its destination and renamed into place, a read-only open).
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError
from primarysource.pkgdocs.model import Doc

SCHEMA_VERSION = 1
MAX_TERMS = 12
WEIGHTS = "0.0, 0.0, 8.0, 1.0"  # doc and sec are not searched; a title match outweighs a body match
_TERM = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Hit:
    doc: str
    section: str
    title: str
    snippet: str
    score: float


def build(path: Path, docs: Sequence[Doc]) -> int:
    """Write the index for `docs` at `path` (which must not exist). Returns the number of sections indexed."""
    rows = 0
    with contextlib.closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.execute(
            "CREATE VIRTUAL TABLE sections USING fts5("
            "doc UNINDEXED, sec UNINDEXED, title, body, tokenize='porter unicode61')"
        )
        for doc in docs:
            for section in doc.sections:
                db.execute(
                    "INSERT INTO sections(doc, sec, title, body) VALUES (?, ?, ?, ?)",
                    (doc.id, section.id, section.title, "\n".join(section.units)),
                )
                rows += 1
        db.commit()
    return rows


def _match(terms: Sequence[str], joiner: str) -> str:
    return f" {joiner} ".join('"' + t.replace('"', '""') + '"' for t in terms)


def search(path: Path, query: str, limit: int = 10, offset: int = 0, doc_prefix: str = "") -> tuple[list[Hit], bool]:
    """Sections matching `query`, best first, and whether the match was relaxed (OR instead of AND). An empty
    list means nothing matched; a missing or unreadable index is a `LibError` that names the remedy."""
    terms = _TERM.findall(query)[:MAX_TERMS]
    if not terms:
        raise LibError(f"nothing to search for in {query!r}", "give at least one word")
    if not path.is_file():
        raise LibError(f"there is no search index at {path}", "", "import the edition again")
    try:
        with contextlib.closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise LibError("the search index has a different schema version", "", "import the edition again")
            for relaxed, joiner in ((False, "AND"), (True, "OR")):
                if relaxed and len(terms) == 1:
                    break
                like = doc_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                found = db.execute(
                    "SELECT doc, sec, title, snippet(sections, 3, '[', ']', ' ... ', 24), "  # noqa: S608
                    f"bm25(sections, {WEIGHTS}) "
                    "FROM sections WHERE sections MATCH ? AND doc LIKE ? ESCAPE '\\' "
                    f"ORDER BY bm25(sections, {WEIGHTS}) LIMIT ? OFFSET ?",
                    (_match(terms, joiner), like, limit, offset),
                ).fetchall()
                if found:
                    return [
                        Hit(str(r[0]), str(r[1]), str(r[2]), " ".join(str(r[3]).split()), float(r[4])) for r in found
                    ], relaxed
    except sqlite3.DatabaseError as exc:
        raise LibError(f"the search index is unreadable ({exc})", "", "import the edition again") from exc
    return [], False
