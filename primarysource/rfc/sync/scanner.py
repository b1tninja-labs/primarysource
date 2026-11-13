"""Bootstrap the file inventory from an rsync-produced local mirror.

Run after scripts/mirror.ps1 completes: walks the mirror directory, finds all
document files (rfcNNNN.txt / bcpNN.html / ... at any nesting depth so both
possible rsync layouts work), hashes them, and registers them in the DB.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .downloader import sha256_file
from .state import register_file

_PREFIX_TO_SERIES = {"rfc": "RFC", "bcp": "BCP", "std": "STD",
                     "fyi": "FYI", "ien": "IEN"}
_FILE_RE = re.compile(
    r"^(rfc|bcp|std|fyi|ien)(\d{1,5})\.(txt|html|xml|pdf|json)$", re.IGNORECASE)


def scan_mirror(conn: sqlite3.Connection, mirror_root: Path) -> dict:
    stats = {"scanned": 0, "registered": 0, "skipped_unmatched": 0, "skipped_unknown_doc": 0}
    has_docs = conn.execute("SELECT COUNT(*) c FROM docs").fetchone()["c"] > 0
    batch: list[tuple] = []
    for path in mirror_root.rglob("*"):
        if not path.is_file():
            continue
        m = _FILE_RE.match(path.name)
        if not m:
            stats["skipped_unmatched"] += 1
            continue
        doc_id = _PREFIX_TO_SERIES[m.group(1).lower()] + m.group(2)
        fmt = m.group(3).lower()
        # Only register docs known from the manifest (guards against stray
        # files); if the manifest hasn't been loaded yet, register everything.
        if has_docs and not conn.execute(
                "SELECT 1 FROM docs WHERE doc_id = ?", (doc_id,)).fetchone():
            stats["skipped_unknown_doc"] += 1
            continue
        batch.append((doc_id, fmt, str(path), sha256_file(path), path.stat().st_size))
        stats["scanned"] += 1

    for doc_id, fmt, pth, digest, size in batch:
        register_file(conn, doc_id, fmt, pth, digest, size, None, "mirror-scan")
        stats["registered"] += 1
    conn.commit()
    return stats
