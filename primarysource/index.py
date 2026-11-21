"""The keyword index every collection shares: SQLite FTS5, ranked by BM25 (PLAN.md §3, §5.7).

One database per collection. Its shape:

- `documents`: one row per document (id, title, declared unit, section count).
- `sections`: one row per section, in reading order, with the section's units joined into a body.
- `sections_fts`: an external-content FTS5 table over `sections` (document title, section title, body), kept in
  step by triggers, tokenized `porter unicode61` so `encoded` finds `encoding` and `resume` finds `résumé`.

How it is opened is the point of most of this module:

- **Readers** (`open_read`) open `?mode=ro` and never create or migrate anything, so a shared server can run on a
  read-only volume and can never damage the index it serves.
- **Writers** (`open_write`) use WAL and a busy timeout, and `index_document` holds `BEGIN IMMEDIATE` around each
  document, so two writers queue for the lock up front instead of failing half-way through.
- **Both** check `PRAGMA user_version` against `SCHEMA_VERSION` and refuse a mismatch with a `LibError` whose
  hint is the collection's rebuild command. There are no migrations: an index is derived data, rebuilt from the
  corpus.
- **A rebuild** (`rebuild`) writes a temporary file in the same directory and `os.replace`s it over the old index,
  so a reader sees the old index or the new one, never a half-built one.

Search (`search`) quotes every user term (`fts_query`), so FTS5 syntax in a question cannot raise. A dotted
numeric identifier is that quoted phrase with a prefix marker on its last component, so `9.8.7.6.5` also
matches a longer identifier such as `9.8.7.6.50`. It asks for every term first; only when nothing has them
all does it ask for any term, and says so with `relaxed`.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError
from primarysource.model import Document

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 15_000

# Statements, not one script: `executescript` commits first, and the schema is created inside the writer's
# `BEGIN IMMEDIATE` so two processes creating the same new index cannot both do it.
_SCHEMA = (
    "CREATE TABLE documents("
    "doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, unit TEXT NOT NULL, sections INTEGER NOT NULL)",
    "CREATE TABLE sections("
    "id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL, section_id TEXT NOT NULL, ord INTEGER NOT NULL, "
    "depth INTEGER NOT NULL, doc_title TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL)",
    "CREATE INDEX sections_doc ON sections(doc_id, ord)",
    "CREATE VIRTUAL TABLE sections_fts USING fts5("
    "doc_title, title, body, content='sections', content_rowid='id', tokenize='porter unicode61')",
    "CREATE TRIGGER sections_ai AFTER INSERT ON sections BEGIN "
    "INSERT INTO sections_fts(rowid, doc_title, title, body) VALUES (new.id, new.doc_title, new.title, new.body); "
    "END",
    "CREATE TRIGGER sections_ad AFTER DELETE ON sections BEGIN "
    "INSERT INTO sections_fts(sections_fts, rowid, doc_title, title, body) "
    "VALUES ('delete', old.id, old.doc_title, old.title, old.body); "
    "END",
    "CREATE TRIGGER sections_au AFTER UPDATE ON sections BEGIN "
    "INSERT INTO sections_fts(sections_fts, rowid, doc_title, title, body) "
    "VALUES ('delete', old.id, old.doc_title, old.title, old.body); "
    "INSERT INTO sections_fts(rowid, doc_title, title, body) VALUES (new.id, new.doc_title, new.title, new.body); "
    "END",
    f"PRAGMA user_version = {SCHEMA_VERSION}",
)


# --- opening ---------------------------------------------------------------------------------------------------


def _remedy(rebuild_command: str) -> str:
    return f"run: {rebuild_command}"


def _check_version(conn: sqlite3.Connection, path: Path, rebuild_command: str) -> None:
    """Refuse an index built by another schema version, or a file that is not an index at all."""
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as error:
        raise LibError(f"{path} is not a readable index: {error}", _remedy(rebuild_command)) from error
    if version != SCHEMA_VERSION:
        raise LibError(
            f"the index at {path} has schema version {version}; this primarysource reads version {SCHEMA_VERSION}",
            _remedy(rebuild_command),
        )


def open_read(path: Path, *, rebuild_command: str, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """A query connection: `?mode=ro`, no schema setup, version checked.

    The file must already exist; a missing index is an error naming `rebuild_command`, never an empty database
    created on the spot. A reader still waits up to `busy_timeout_ms` for a writer.
    """
    if not path.is_file():
        raise LibError(f"no index at {path}", _remedy(rebuild_command))
    try:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=busy_timeout_ms / 1000, isolation_level=None
        )
    except sqlite3.Error as error:
        raise LibError(f"cannot open the index at {path}: {error}", _remedy(rebuild_command)) from error
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        _check_version(conn, path, rebuild_command)
    except BaseException:
        conn.close()
        raise
    return conn


def _has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is not None


def _connect_write(path: Path, busy_timeout_ms: int) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: transactions are begun and ended here, explicitly, never implicitly by the driver.
    conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    return conn


def open_write(path: Path, *, rebuild_command: str, busy_timeout_ms: int = BUSY_TIMEOUT_MS) -> sqlite3.Connection:
    """A writer connection: WAL, a busy timeout, and the schema created if the file is new.

    A file that is neither new nor at `SCHEMA_VERSION` is refused with a hint naming `rebuild_command`.
    """
    conn = _connect_write(path, busy_timeout_ms)
    try:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.DatabaseError as error:
            raise LibError(f"{path} is not a writable index: {error}", _remedy(rebuild_command)) from error
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and not _has_tables(conn):
                for statement in _SCHEMA:
                    conn.execute(statement)
            else:
                _check_version(conn, path, rebuild_command)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    except BaseException:
        conn.close()
        raise
    return conn


# --- writing ---------------------------------------------------------------------------------------------------


def _write_document(conn: sqlite3.Connection, document: Document) -> int:
    conn.execute("DELETE FROM sections WHERE doc_id = ?", (document.id,))
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (document.id,))
    conn.executemany(
        "INSERT INTO sections(doc_id, section_id, ord, depth, doc_title, title, body) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (document.id, section.id, ord_, section.depth, document.title, section.title, "\n\n".join(section.units))
            for ord_, section in enumerate(document.sections)
        ],
    )
    conn.execute(
        "INSERT INTO documents(doc_id, title, unit, sections) VALUES (?, ?, ?, ?)",
        (document.id, document.title, str(document.unit), len(document.sections)),
    )
    return len(document.sections)


def index_document(conn: sqlite3.Connection, document: Document) -> int:
    """Replace one document's sections; returns how many were written.

    Runs under `BEGIN IMMEDIATE`, so the write lock is taken before anything is read and a second writer waits
    (up to the busy timeout) at the start instead of colliding in the middle. A failure rolls the whole document
    back. Called inside a transaction the caller already holds, it joins that transaction and leaves the commit to
    the caller.
    """
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        written = _write_document(conn, document)
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    return written


def remove_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    """Drop one document; True if it was there."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM sections WHERE doc_id = ?", (doc_id,))
        removed = conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,)).rowcount > 0
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own:
            conn.execute("ROLLBACK")
        raise
    return removed


def _quiesce(path: Path, rebuild_command: str, busy_timeout_ms: int) -> None:
    """Empty the old index's WAL before it is replaced, or refuse.

    A `-wal` file belongs to a database by name, not by content: frames left in `<index>-wal` would be replayed
    onto the new file the next time a writer opens it. So the old WAL is checkpointed and truncated first, and if
    a reader's open transaction prevents that, the rebuild stops with the old index untouched.
    """
    if not path.is_file():
        return
    try:
        conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, isolation_level=None)
    except sqlite3.Error:
        return
    try:
        conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        busy, _, _ = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.DatabaseError:
        return  # not a database: nothing of it can be replayed, so it may simply be replaced
    finally:
        conn.close()
    if busy:
        raise LibError(
            f"the index at {path} is being read, so its write-ahead log cannot be emptied before the rebuild",
            f"retry when it is idle, or stop the servers reading it and run: {rebuild_command}",
        )


def rebuild(
    path: Path,
    documents: Iterable[Document],
    *,
    rebuild_command: str,
    busy_timeout_ms: int = BUSY_TIMEOUT_MS,
) -> int:
    """Build a fresh index from `documents` and swap it in atomically; returns the number of sections.

    The new index is written to a temporary file beside `path` and moved over it with `os.replace`, so readers see
    the old index or the new one and never a partial one. If building fails, the old index is left as it was and
    the temporary file is removed. The new file is published in rollback-journal mode, so a `mode=ro` reader on a
    read-only volume can open it without creating `-wal`/`-shm` files; the next `open_write` switches it to WAL.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(handle)
    temporary = Path(name)
    try:
        conn = _connect_write(temporary, busy_timeout_ms)
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA:
                conn.execute(statement)
            written = sum(_write_document(conn, document) for document in documents)
            conn.execute("INSERT INTO sections_fts(sections_fts) VALUES ('optimize')")
            conn.execute("COMMIT")
        finally:
            conn.close()
        _quiesce(path, rebuild_command, busy_timeout_ms)
        try:
            os.replace(temporary, path)
        except PermissionError as error:
            raise LibError(
                f"cannot replace the index at {path} while another process has it open: {error}",
                f"stop the servers reading it, then run: {rebuild_command}",
            ) from error
    except BaseException:
        temporary.unlink(missing_ok=True)
        Path(f"{temporary}-journal").unlink(missing_ok=True)
        raise
    return written


# --- querying --------------------------------------------------------------------------------------------------

# Filler that must not be a required term: "how is the value encoded" should not demand a section containing
# "how", "is" and "the". A query made only of filler is still searched as typed. `and` and `or` typed as operators
# are filler too; `not` is kept, because in a specification it is the word that matters.
_FILLER = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "do",
        "does",
        "did",
        "and",
        "or",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
    ]
)
_WORD = re.compile(r"\w")
_DOTTED_ID = re.compile(r"\d+(?:\.\d+)+")
_TERM_PUNCT = "?.,;:!()\"'"


def query_terms(raw: str) -> tuple[str, ...]:
    """The searchable terms of `raw`: whitespace-separated tokens holding a word character, filler dropped."""
    tokens = [token for token in raw.split() if _WORD.search(token)]
    content = [token for token in tokens if token.strip(_TERM_PUNCT).lower() not in _FILLER]
    return tuple(dict.fromkeys(content or tokens))


def _fts_term(term: str) -> str:
    """One MATCH term. Quotes are doubled so the term cannot be read as FTS5 syntax.

    `porter unicode61` splits on `.`. Quoting `9.8.7.6.5` as one phrase finds that exact sequence of tokens.
    A longer identifier such as `9.8.7.6.50` shares every component except the last, which only begins with
    the queried component, so the last token is a prefix. The same rule matches `1.2` inside `1.20`.
    """
    core = term.strip(_TERM_PUNCT)
    if _DOTTED_ID.fullmatch(core):
        return '"' + core.replace('"', '""') + '"*'
    return '"' + term.replace('"', '""') + '"'


def fts_query(raw: str, *, any_term: bool = False) -> str:
    """A MATCH expression that FTS5 accepts whatever the user typed.

    Every term is quoted as a phrase, with internal double quotes doubled (FTS5's own escape), so `set-of`,
    `NEAR(`, `title:x`, `a*` and a stray `"` are searched as words instead of parsed as operators. A dotted
    numeric identifier keeps that quoting and adds a prefix marker (`_fts_term`). Terms are ANDed, or ORed
    with `any_term`. The trade is stated rather than hidden: FTS5 syntax does not work from a query box.
    """
    terms = query_terms(raw)
    if not terms:
        raise LibError("the query has no words to search for", "pass at least one word")
    joiner = " OR " if any_term else " "
    return joiner.join(_fts_term(term) for term in terms)


@dataclass(frozen=True, slots=True)
class Hit:
    """One matching section. `score` is higher-is-better: BM25 negated, times the collection's adjustment."""

    doc_id: str
    section_id: str
    doc_title: str
    title: str
    snippet: str
    score: float


RankAdjust = Callable[[Hit, str], float]
"""Given a hit and the raw query, a factor for its score: below 1 demotes, above 1 promotes (itulib demotes
definitions and informative annexes by 0.6 unless the query asks what a term means)."""


@dataclass(frozen=True, slots=True)
class Ranking:
    """A collection's ranking: BM25 column weights and an optional adjustment of each hit.

    `candidates` is how many BM25 hits beyond the requested page are fetched for `adjust` to reorder.
    """

    doc_title: float = 1.0
    title: float = 4.0
    body: float = 1.0
    adjust: RankAdjust | None = None
    candidates: int = 200

    def bm25(self) -> str:
        # Floats formatted here, never user text: the weights are part of the SQL, as bm25() requires constants.
        return f"bm25(sections_fts, {float(self.doc_title)!r}, {float(self.title)!r}, {float(self.body)!r})"


@dataclass(frozen=True, slots=True)
class SearchResult:
    """`relaxed` is true when no section held every term and these hits hold only some of them.

    `next_start` is the `start` for the next page, or None at the end. No hits means nothing matched.
    """

    hits: tuple[Hit, ...]
    relaxed: bool
    next_start: int | None


def _match(conn: sqlite3.Connection, expression: str, ranking: Ranking, fetch: int) -> list[Hit]:
    order = ranking.bm25()
    rows = conn.execute(
        "SELECT s.doc_id, s.section_id, s.doc_title, s.title, "  # noqa: S608 - only formatted floats are interpolated
        f"snippet(sections_fts, 2, '', '', ' … ', 24), {order} "
        "FROM sections_fts JOIN sections AS s ON s.id = sections_fts.rowid "
        f"WHERE sections_fts MATCH ? ORDER BY {order}, s.id LIMIT ?",
        (expression, fetch),
    ).fetchall()
    return [Hit(row[0], row[1], row[2], row[3], row[4] or row[3], -row[5]) for row in rows]


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    ranking: Ranking | None = None,
    limit: int = 8,
    start: int = 0,
) -> SearchResult:
    """The best sections for `query`, best first, `limit` from `start`.

    Every term is required first. If no section holds them all and there is more than one term, any term will do
    and the result says `relaxed`. `ranking.adjust`, when given, rescales each candidate and the candidates are
    re-sorted before the page is cut.
    """
    ranking = ranking or Ranking()
    fetch = start + limit + ranking.candidates
    strict = fts_query(query)
    hits = _match(conn, strict, ranking, fetch)
    relaxed = False
    if not hits:
        loose = fts_query(query, any_term=True)
        if loose != strict:
            hits = _match(conn, loose, ranking, fetch)
            relaxed = bool(hits)
    if ranking.adjust is not None:
        adjust = ranking.adjust
        hits = [
            Hit(hit.doc_id, hit.section_id, hit.doc_title, hit.title, hit.snippet, hit.score * adjust(hit, query))
            for hit in hits
        ]
        hits.sort(key=lambda hit: -hit.score)  # stable: equal scores keep BM25 order
    page = tuple(hits[start : start + limit])
    more = len(hits) > start + limit
    return SearchResult(page, relaxed, start + len(page) if more else None)
