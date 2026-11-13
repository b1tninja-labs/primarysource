"""The local SQLite index: one row per CVE per source, so records merge when read, not when loaded.

Merging at read time means the order sources were synced in cannot change an answer, and a later source (NVD, OSV)
adds rows instead of rewriting them.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import config
from .errors import CvelibError
from .kernel import Pair
from .parse import KevEntry, Record

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS source(
    name TEXT PRIMARY KEY, state TEXT NOT NULL, version TEXT, upstream_date TEXT, synced_at TEXT,
    records INTEGER, detail TEXT, etag TEXT
);
CREATE TABLE IF NOT EXISTS record(
    rowid INTEGER PRIMARY KEY,
    cve TEXT NOT NULL, source TEXT NOT NULL, state TEXT NOT NULL, assigner TEXT, assigner_org TEXT,
    published TEXT, updated TEXT, title TEXT, description TEXT, products TEXT, files TEXT,
    cwes TEXT, refs TEXT, affected TEXT, ssvc TEXT,
    UNIQUE(cve, source)
);
CREATE INDEX IF NOT EXISTS record_cve ON record(cve);
CREATE TABLE IF NOT EXISTS metric(
    cve TEXT NOT NULL, source TEXT NOT NULL, label TEXT NOT NULL, version TEXT NOT NULL, vector TEXT NOT NULL,
    score REAL, severity TEXT
);
CREATE INDEX IF NOT EXISTS metric_cve ON metric(cve, source);
CREATE TABLE IF NOT EXISTS kev(
    cve TEXT PRIMARY KEY, vendor TEXT, product TEXT, name TEXT, date_added TEXT, due_date TEXT, ransomware TEXT,
    action TEXT, description TEXT, notes TEXT, cwes TEXT, forensic_triage TEXT
);
CREATE INDEX IF NOT EXISTS kev_added ON kev(date_added);
CREATE TABLE IF NOT EXISTS epss(cve TEXT PRIMARY KEY, score REAL NOT NULL, percentile REAL NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS kernel_pair(
    cve TEXT NOT NULL, start TEXT NOT NULL, start_git TEXT, fix TEXT NOT NULL, fix_git TEXT
);
CREATE INDEX IF NOT EXISTS kernel_pair_cve ON kernel_pair(cve);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    title, description, products, files, content='record', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS record_ai AFTER INSERT ON record BEGIN
    INSERT INTO fts(rowid, title, description, products, files)
    VALUES (new.rowid, new.title, new.description, new.products, new.files);
END;
CREATE TRIGGER IF NOT EXISTS record_ad AFTER DELETE ON record BEGIN
    INSERT INTO fts(fts, rowid, title, description, products, files)
    VALUES ('delete', old.rowid, old.title, old.description, old.products, old.files);
END;
"""


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def open_write(path: Path | None = None) -> sqlite3.Connection:
    target = path or config.index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = _configure(sqlite3.connect(target))
    # WAL lets an MCP server keep reading while a sync writes. If the filesystem cannot do it, the default holds.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


def open_read(path: Path | None = None) -> sqlite3.Connection:
    target = path or config.index_path()
    if not target.is_file():
        raise CvelibError(
            f"no cve index at {target}",
            "Run: primarysource cve sync   (set CVELIB_HOME to a large disk first; see primarysource cve path)",
            status="not_synced",
        )
    try:
        conn = _configure(sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True))
        conn.execute("SELECT 1 FROM source LIMIT 1")
    except sqlite3.Error as error:
        raise CvelibError(
            f"the index at {target} is unusable: {error}", "Run: primarysource cve sync --rebuild"
        ) from error
    return conn


def mark_source(
    conn: sqlite3.Connection,
    name: str,
    state: str,
    version: str | None = None,
    upstream_date: str | None = None,
    records: int | None = None,
    detail: str | None = None,
    etag: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO source(name, state, version, upstream_date, synced_at, records, detail, etag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET state=excluded.state, "
        "version=COALESCE(excluded.version, source.version), "
        "upstream_date=COALESCE(excluded.upstream_date, source.upstream_date), "
        "synced_at=excluded.synced_at, records=COALESCE(excluded.records, source.records), detail=excluded.detail, "
        "etag=COALESCE(excluded.etag, source.etag)",
        (name, state, version, upstream_date, now_iso(), records, detail, etag),
    )
    conn.commit()


def source_row(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM source WHERE name=?", (name,)).fetchone()
    return row


def existing_updated(conn: sqlite3.Connection, source: str) -> dict[str, str]:
    return {row[0]: row[1] or "" for row in conn.execute("SELECT cve, updated FROM record WHERE source=?", (source,))}


def put_record(conn: sqlite3.Connection, source: str, record: Record) -> None:
    conn.execute("DELETE FROM record WHERE cve=? AND source=?", (record.cve, source))
    conn.execute("DELETE FROM metric WHERE cve=? AND source=?", (record.cve, source))
    products = " ".join(sorted({f"{a.get('vendor', '')} {a.get('product', '')}".strip() for a in record.affected}))
    conn.execute(
        "INSERT INTO record(cve, source, state, assigner, assigner_org, published, updated, title, description, "
        "products, files, cwes, refs, affected, ssvc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.cve,
            source,
            record.state,
            record.assigner,
            record.assigner_org,
            record.published,
            record.updated,
            record.title,
            record.description,
            products,
            " ".join(record.program_files),
            json.dumps(record.cwes),
            json.dumps(record.references),
            json.dumps(record.affected, separators=(",", ":")),
            json.dumps(record.ssvc) if record.ssvc else None,
        ),
    )
    conn.executemany(
        "INSERT INTO metric(cve, source, label, version, vector, score, severity) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(record.cve, source, m.label, m.version, m.vector, m.score, m.severity) for m in record.metrics],
    )


def replace_kev(conn: sqlite3.Connection, entries: list[KevEntry]) -> None:
    conn.execute("DELETE FROM kev")
    conn.executemany(
        "INSERT OR REPLACE INTO kev VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                e.cve,
                e.vendor,
                e.product,
                e.name,
                e.date_added,
                e.due_date,
                e.ransomware,
                e.action,
                e.description,
                e.notes,
                json.dumps(e.cwes),
                e.forensic_triage,
            )
            for e in entries
        ],
    )


def replace_epss(conn: sqlite3.Connection, rows: Iterable[tuple[str, float, float]]) -> None:
    conn.execute("DELETE FROM epss")
    conn.executemany("INSERT OR REPLACE INTO epss(cve, score, percentile) VALUES (?, ?, ?)", rows)


def clear_kernel(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM kernel_pair")
    conn.execute("DELETE FROM record WHERE source='kernel'")
    conn.execute("DELETE FROM metric WHERE source='kernel'")


def put_pairs(conn: sqlite3.Connection, cve: str, pairs: list[Pair]) -> None:
    conn.executemany(
        "INSERT INTO kernel_pair(cve, start, start_git, fix, fix_git) VALUES (?, ?, ?, ?, ?)",
        [(cve, ".".join(map(str, p.start)), p.start_git, ".".join(map(str, p.fix)), p.fix_git) for p in pairs],
    )


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
