"""SQLite state: document metadata, relation graph, local file inventory."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from .manifest import DocMeta

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  doc_id         TEXT PRIMARY KEY,
  series         TEXT NOT NULL,
  title          TEXT,
  authors        TEXT,               -- JSON list
  pub_date       TEXT,               -- ISO YYYY-MM-01
  status         TEXT,               -- publication status at publication
  current_status TEXT,               -- status today
  stream         TEXT,
  wg             TEXT,
  area           TEXT,
  doi            TEXT,
  errata_url     TEXT,
  page_count     INTEGER,
  keywords       TEXT,
  abstract       TEXT,
  formats        TEXT,               -- JSON list of formats offered upstream
  draft_name     TEXT,
  is_current     INTEGER NOT NULL DEFAULT 1,
  synced_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_pub ON docs(pub_date DESC);
CREATE INDEX IF NOT EXISTS idx_docs_series ON docs(series);

CREATE TABLE IF NOT EXISTS doc_relations(
  src  TEXT NOT NULL,
  dst  TEXT NOT NULL,
  kind TEXT NOT NULL,                -- obsoletes|obsoleted_by|updates|updated_by|alias
  PRIMARY KEY (src, dst, kind)
);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON doc_relations(dst, kind);

CREATE TABLE IF NOT EXISTS files(
  doc_id     TEXT NOT NULL,
  fmt        TEXT NOT NULL,          -- txt|html|xml|pdf|json
  path       TEXT NOT NULL,
  sha256     TEXT,
  size       INTEGER,
  source_url TEXT,
  fetched_at TEXT,
  origin     TEXT,                   -- 'http' | 'mirror-scan'
  PRIMARY KEY (doc_id, fmt)
);

CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
  doc_id UNINDEXED, title, abstract, keywords,
  tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS chunks(
  id         INTEGER PRIMARY KEY,
  doc_id     TEXT NOT NULL,
  sec_num    TEXT NOT NULL,              -- '1','4.2','Appendix A','' = front matter
  sec_title  TEXT NOT NULL,
  start_line INTEGER NOT NULL,           -- 1-based line range in the .txt file
  end_line   INTEGER NOT NULL,
  body       TEXT NOT NULL,              -- junk-stripped section text
  sha256     TEXT NOT NULL,              -- content hash (embed staleness)
  -- External-content FTS5 maps by COLUMN NAME, so provide the names:
  sec        TEXT GENERATED ALWAYS AS (trim(sec_num || ' ' || sec_title)) STORED
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS chunk_src(
  doc_id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL                   -- source-file hash; skip unchanged
);

CREATE TABLE IF NOT EXISTS embed_state(
  chunk_id INTEGER PRIMARY KEY,
  sha      TEXT NOT NULL,
  model    TEXT,
  at       TEXT
);

-- Cross-reference graph mined from RFC txt sources (see rfclib.graph).
-- kind: normative|informative|reference (References-section tag) or
-- mention (section-anchored reference found anywhere in the body).
-- sec: referenced section number, '' when the citation is whole-doc.
CREATE TABLE IF NOT EXISTS ref_edges(
  src  TEXT NOT NULL,
  dst  TEXT NOT NULL,
  kind TEXT NOT NULL,
  sec  TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (src, dst, kind, sec)
);
CREATE INDEX IF NOT EXISTS idx_refs_dst ON ref_edges(dst, kind);
CREATE INDEX IF NOT EXISTS idx_refs_src ON ref_edges(src, kind);

CREATE TABLE IF NOT EXISTS ref_src(
  doc_id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL              -- source .txt hash; skip unchanged
);

-- Verified/reported errata cached from the RFC Editor errata service
-- (errata.rfc-editor.org); fetched per document on demand, never bulk.
CREATE TABLE IF NOT EXISTS errata(
  eid           INTEGER PRIMARY KEY,
  doc_id        TEXT NOT NULL,
  status        TEXT NOT NULL,       -- Verified|Reported|Held for Document Update|Rejected
  type          TEXT,                -- Technical|Editorial
  section       TEXT,
  says          TEXT,
  should_say    TEXT,
  notes         TEXT,
  reported_by   TEXT,
  reported_date TEXT,
  handler       TEXT,                -- verified/rejected by
  handler_date  TEXT,
  fetched_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_errata_doc ON errata(doc_id, status);

-- Citations made BY a project (code or docs) INTO this library, recorded so
-- drift is detectable: rfclib.cite.lint re-checks them after a sync and
-- reports obsolete targets, vanished sections or changed span text. Storing
-- the span hash is what makes "did the spec move under this comment?" a
-- lookup instead of a re-reading job.
CREATE TABLE IF NOT EXISTS citations(
  id         INTEGER PRIMARY KEY,
  project    TEXT NOT NULL,           -- label, e.g. 'rwhois' or a file path
  location   TEXT NOT NULL,           -- 'path:lineno' or 'module.symbol'
  doc_id     TEXT NOT NULL,
  sec_num    TEXT NOT NULL DEFAULT '',
  span_sha   TEXT NOT NULL DEFAULT '', -- span_hash of the cited text, '' = doc-wide
  note       TEXT,
  status     TEXT,                    -- ok|obsolete|missing-section|drift
  checked_at TEXT,
  UNIQUE (project, location, doc_id, sec_num)
);
CREATE INDEX IF NOT EXISTS idx_cite_doc ON citations(doc_id, sec_num);

-- Paragraph-level structure from RFCXML v3 (RFC 8650+; rfclib.index.rfcxml).
-- pn is the RFC Editor's own block id and HTML anchor ('section-9.6-3');
-- start/end_line point into the .txt exactly like chunks do. exact=0 means
-- the range was interpolated between aligned neighbours.
CREATE TABLE IF NOT EXISTS blocks(
  doc_id     TEXT NOT NULL,
  pn         TEXT NOT NULL,
  ord        INTEGER NOT NULL,           -- document order
  kind       TEXT NOT NULL,              -- t|ul|ol|dl|sourcecode|artwork|table|reference|author|...
  sec_num    TEXT NOT NULL,              -- same vocabulary as chunks.sec_num
  sec_title  TEXT NOT NULL,
  sec_anchor TEXT NOT NULL DEFAULT '',   -- author anchor, e.g. 'migration'
  start_line INTEGER NOT NULL,
  end_line   INTEGER NOT NULL,
  text       TEXT NOT NULL,
  bcp14      TEXT NOT NULL DEFAULT '',   -- 'MUST,SHOULD NOT' from <bcp14>
  lang       TEXT NOT NULL DEFAULT '',   -- sourcecode/artwork type ('abnf')
  exact      INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (doc_id, pn)
);
CREATE INDEX IF NOT EXISTS idx_blocks_sec ON blocks(doc_id, sec_num);

-- Section-precise citations from <xref target=REF section="7.7">: which
-- block of doc_id cites which section of dst_doc ('' = whole document).
CREATE TABLE IF NOT EXISTS xrefs(
  doc_id     TEXT NOT NULL,
  src_pn     TEXT NOT NULL,
  src_sec    TEXT NOT NULL,
  dst_doc    TEXT NOT NULL,
  dst_sec    TEXT NOT NULL DEFAULT '',
  ref_anchor TEXT NOT NULL,              -- bib anchor, e.g. 'QUIC-RECOVERY'
  normative  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (doc_id, src_pn, dst_doc, dst_sec)
);
CREATE INDEX IF NOT EXISTS idx_xrefs_dst ON xrefs(dst_doc, dst_sec);

-- How each document was segmented (rfclib.index.txtseg for txt-only docs,
-- 'rfcxml' for RFC 8650+). score = ToC entries located in the body / ToC
-- entries (NULL when the document has no usable ToC): the review list for
-- segmentations that may be wrong.
CREATE TABLE IF NOT EXISTS seg_quality(
  doc_id      TEXT PRIMARY KEY,
  method      TEXT NOT NULL,             -- rfcxml | toc | scan | legacy
  toc_entries INTEGER NOT NULL DEFAULT 0,
  matched     INTEGER NOT NULL DEFAULT 0,
  extra       INTEGER NOT NULL DEFAULT 0, -- headings deeper than the ToC lists
  headings    INTEGER NOT NULL DEFAULT 0,
  score       REAL,
  notes       TEXT NOT NULL DEFAULT ''
);

-- Identifier tokens per section (rfclib.index.lexical): '_' and '-' stay
-- inside tokens, no stemming, so "preferred_address" matches only itself.
-- rowid == chunks.id; ident_none marks sections with nothing to index.
CREATE VIRTUAL TABLE IF NOT EXISTS ident_fts USING fts5(
  terms, tokenize = "unicode61 tokenchars '_-' remove_diacritics 0"
);
CREATE TABLE IF NOT EXISTS ident_none(chunk_id INTEGER PRIMARY KEY);

-- "Network Time Protocol (NTP)" pairs mined from the corpus; a query
-- acronym also matches its expansion.
CREATE TABLE IF NOT EXISTS acronyms(
  acro      TEXT PRIMARY KEY,         -- 'NTP'
  expansion TEXT NOT NULL,            -- 'network time protocol'
  n         INTEGER NOT NULL          -- times seen
);

-- External-content FTS5 index over chunk bodies; rowid == chunks.id.
-- Rebuild with: INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  sec, body, content='chunks', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2'
);
"""


def open_db(path: Path, read_only: bool = False) -> sqlite3.Connection:
    """read_only: open with SQLite's mode=ro and skip schema creation and
    migrations, for a server that must never write (the library has to
    exist already). Readers still wait for a writer via busy_timeout."""
    if read_only:
        try:
            conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro",
                                   uri=True, timeout=30)
        except sqlite3.OperationalError as e:
            raise sqlite3.OperationalError(
                f"{e}: {path} (a read-only server needs an existing "
                "library; run `rfclib init` or start the shared server "
                "first)") from None
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
    path.parent.mkdir(parents=True, exist_ok=True)
    # Several processes share one library (an MCP server per client session,
    # plus `rfclib sync`): wait for a writer instead of failing at once.
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    # Migration: old chunks schema lacked the name-mapped FTS columns.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(chunks)")]
    if cols and "body" not in cols:
        conn.executescript(
            "DROP TABLE IF EXISTS chunks_fts; DROP TABLE IF EXISTS chunks;"
            "DROP TABLE IF EXISTS chunk_src; DELETE FROM embed_state;")
    conn.executescript(SCHEMA)
    if get_meta(conn, "files_paths") != "relative":
        _relativize_paths(conn)
    # every table a read path expects exists once a writer has opened the
    # library, so a read-only server never has to create one
    from ..subjects import ensure_schema as _subjects_schema
    _subjects_schema(conn)
    return conn


# --------------------------------------------------------------------------
# file paths: stored relative to <home>/mirror in POSIX form ('rfc/rfc9000.txt')
# so one library works after a move, on another OS, or mounted in a container.
# Absolute paths (files registered from outside the mirror) are kept as-is.

def _is_abs(stored: str) -> bool:
    return PureWindowsPath(stored).is_absolute() or stored.startswith("/")


def mirror_of(conn: sqlite3.Connection) -> Path:
    """<home>/mirror for the library this connection belongs to."""
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2]).parent / "mirror"


def stored_path(conn: sqlite3.Connection, path: Path | str) -> str:
    """The form a file path is recorded in: relative to the mirror when the
    file lives under it, else absolute."""
    p = Path(path)
    try:
        return p.resolve().relative_to(mirror_of(conn).resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


def file_path(conn: sqlite3.Connection, stored: str,
              mirror: Path | None = None) -> Path:
    """Resolve a recorded files.path to a real path on this machine."""
    if _is_abs(stored):
        return Path(stored)
    return (mirror or mirror_of(conn)) / PurePosixPath(stored)


def _relativize_paths(conn: sqlite3.Connection) -> None:
    """One-time migration of absolute paths written by older versions
    ('D:\\code\\rfclibrary\\data\\mirror\\rfc\\rfc9000.txt', '/home/mirror/...'):
    everything after the last 'mirror' path segment becomes the relative
    path, whichever OS wrote it."""
    rows = conn.execute("SELECT doc_id, fmt, path FROM files").fetchall()
    upd = []
    for r in rows:
        s = r["path"] or ""
        if not _is_abs(s):
            continue
        parts = [x for x in re.split(r"[\\/]+", s) if x]
        if "mirror" in parts:
            i = len(parts) - 1 - parts[::-1].index("mirror")
            if i + 1 < len(parts):
                upd.append(("/".join(parts[i + 1:]), r["doc_id"], r["fmt"]))
    conn.executemany("UPDATE files SET path=? WHERE doc_id=? AND fmt=?", upd)
    set_meta(conn, "files_paths", "relative")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def upsert_docs(conn: sqlite3.Connection, docs: Iterable[DocMeta]) -> tuple[int, int]:
    now = _now()
    doc_rows, rel_rows, ids = [], [], []
    for d in docs:
        ids.append(d.doc_id)
        doc_rows.append((
            d.doc_id, d.series, d.title, json.dumps(d.authors), d.pub_date,
            d.status, d.current_status, d.stream, d.wg, d.area, d.doi,
            d.errata_url, d.page_count, " ".join(d.keywords), d.abstract,
            json.dumps(d.formats), d.draft_name, 1, now,
        ))
        for kind, target in d.relations:
            rel_rows.append((d.doc_id, target, kind))

    conn.executemany(
        """INSERT INTO docs(doc_id, series, title, authors, pub_date, status,
                            current_status, stream, wg, area, doi, errata_url,
                            page_count, keywords, abstract, formats, draft_name,
                            is_current, synced_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(doc_id) DO UPDATE SET
             series=excluded.series, title=excluded.title, authors=excluded.authors,
             pub_date=excluded.pub_date, status=excluded.status,
             current_status=excluded.current_status, stream=excluded.stream,
             wg=excluded.wg, area=excluded.area, doi=excluded.doi,
             errata_url=excluded.errata_url, page_count=excluded.page_count,
             keywords=excluded.keywords, abstract=excluded.abstract,
             formats=excluded.formats, draft_name=excluded.draft_name,
             synced_at=excluded.synced_at""",
        doc_rows,
    )
    if ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM doc_relations WHERE src IN ({placeholders})", ids)
    conn.executemany(
        "INSERT OR IGNORE INTO doc_relations(src, dst, kind) VALUES(?,?,?)", rel_rows
    )
    conn.commit()
    return len(doc_rows), len(rel_rows)


def refresh_current_flags(conn: sqlite3.Connection) -> int:
    """A doc is not current if the manifest says it was obsoleted."""
    conn.execute("UPDATE docs SET is_current = 1")
    cur = conn.execute(
        """UPDATE docs SET is_current = 0 WHERE doc_id IN (
             SELECT src FROM doc_relations WHERE kind = 'obsoleted_by')"""
    )
    conn.commit()
    return cur.rowcount


def rebuild_fts(conn: sqlite3.Connection) -> int:
    conn.execute("DELETE FROM docs_fts")
    conn.execute(
        """INSERT INTO docs_fts(doc_id, title, abstract, keywords)
           SELECT doc_id, COALESCE(title,''), COALESCE(abstract,''),
                  COALESCE(keywords,'')
           FROM docs WHERE series = 'RFC' OR title IS NOT NULL"""
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM docs_fts").fetchone()[0]


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def register_file(conn: sqlite3.Connection, doc_id: str, fmt: str,
                  path: Path | str, sha256: str | None, size: int | None,
                  source_url: str | None, origin: str) -> None:
    path = stored_path(conn, path)
    conn.execute(
        """INSERT INTO files(doc_id, fmt, path, sha256, size, source_url, fetched_at, origin)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(doc_id, fmt) DO UPDATE SET
             path=excluded.path, sha256=excluded.sha256, size=excluded.size,
             source_url=excluded.source_url, fetched_at=excluded.fetched_at,
             origin=excluded.origin""",
        (doc_id, fmt, path, sha256, size, source_url, _now(), origin),
    )


def missing_docs(conn: sqlite3.Connection, fmts: list[str],
                 include_obsolete: bool = False) -> list[str]:
    """doc_ids of series docs whose local copy of EVERY requested format is absent.

    Docs whose manifest `formats` list offers none of the requested formats
    are skipped: asking for xml would otherwise 404 on ~8,800 pre-RFC8650
    documents that were never published in RFCXML. An empty list (BCP/STD/
    FYI aliases) only ever has a txt rendering upstream."""
    cond = "" if include_obsolete else "AND d.is_current = 1"
    fmt_in = ",".join("?" * len(fmts))
    unknown_ok = "1" if "txt" in fmts else "0"
    rows = conn.execute(
        f"""SELECT d.doc_id FROM docs d
            WHERE d.series IN ('RFC','BCP','STD','FYI') {cond}
              AND (SELECT COUNT(*) FROM files f
                   WHERE f.doc_id = d.doc_id AND f.fmt IN ({fmt_in})) = 0
              AND (CASE WHEN d.formats IS NULL OR d.formats IN ('', '[]')
                        THEN {unknown_ok}
                        ELSE EXISTS (SELECT 1 FROM json_each(d.formats) j
                                     WHERE lower(j.value) IN ({fmt_in}))
                   END)
            ORDER BY d.pub_date DESC, d.doc_id DESC""",
        fmts + fmts,
    ).fetchall()
    return [r["doc_id"] for r in rows]


def db_stats(conn: sqlite3.Connection) -> dict:
    stats: dict = {}
    stats["docs"] = conn.execute("SELECT COUNT(*) c FROM docs").fetchone()["c"]
    stats["by_series"] = {
        r["series"]: r["c"] for r in
        conn.execute("SELECT series, COUNT(*) c FROM docs GROUP BY series")}
    stats["current"] = conn.execute(
        "SELECT COUNT(*) c FROM docs WHERE is_current=1").fetchone()["c"]
    stats["relations"] = conn.execute(
        "SELECT COUNT(*) c FROM doc_relations").fetchone()["c"]
    stats["files_by_fmt"] = {
        r["fmt"]: r["c"] for r in
        conn.execute("SELECT fmt, COUNT(*) c FROM files GROUP BY fmt")}
    stats["files_bytes"] = conn.execute(
        "SELECT COALESCE(SUM(size),0) c FROM files").fetchone()["c"]
    stats["newest_pub_date"] = conn.execute(
        "SELECT MAX(pub_date) m FROM docs").fetchone()["m"]
    stats["manifest_synced_at"] = get_meta(conn, "manifest_synced_at")
    have = conn.execute(
        "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' "
        "AND name='subjects'").fetchone()["c"]
    stats["subjects"] = (conn.execute("SELECT COUNT(*) c FROM subjects")
                         .fetchone()["c"] if have else 0)
    stats["subjects_synced_at"] = get_meta(conn, "subjects_synced_at")
    return stats

