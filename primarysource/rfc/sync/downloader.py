"""Async incremental downloader against the official RFC Editor HTTP site.

The initial bulk pull is expected to come from the official rsync service
(see scripts/mirror.ps1); this module handles incremental updates and can do
a full pull on its own if rsync is unavailable. Files land in the same
rfc-editor.org layout the rsync modules use, so both producers are compatible.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

from ..config import BASE_URL, USER_AGENT, require_network
from ..fsutil import atomic_write_bytes
from .state import file_path, register_file

VALID_FORMATS = ("txt", "html", "xml", "pdf", "json")

_DOC_RE = re.compile(r"^(RFC|BCP|STD|FYI|IEN)(\d+)$")


def doc_relpath(doc_id: str, fmt: str) -> str | None:
    """Local mirror-relative path, matching the rfc-editor module layout."""
    m = _DOC_RE.match(doc_id)
    if not m:
        return None
    series, num = m.group(1).lower(), m.group(2)
    return f"{series}/{series}{num}.{fmt}"


def doc_url(doc_id: str, fmt: str) -> str | None:
    m = _DOC_RE.match(doc_id)
    if not m:
        return None
    series, num = m.group(1).lower(), m.group(2)
    return f"{BASE_URL}/{series}/{series}{num}.{fmt}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _has_local(conn: sqlite3.Connection, doc_id: str, fmt: str) -> bool:
    row = conn.execute(
        "SELECT path FROM files WHERE doc_id=? AND fmt=?", (doc_id, fmt)
    ).fetchone()
    return bool(row) and file_path(conn, row["path"]).exists()


async def _fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                     conn: sqlite3.Connection, mirror_root: Path,
                     doc_id: str, fmt: str) -> tuple[str, str, str]:
    url = doc_url(doc_id, fmt)
    rel = doc_relpath(doc_id, fmt)
    if url is None or rel is None:
        return doc_id, fmt, "skipped:unknown-id"
    dest = mirror_root / rel
    try:
        async with sem:
            r = await client.get(url)
        if r.status_code == 404:
            return doc_id, fmt, "missing:404"
        r.raise_for_status()
        atomic_write_bytes(dest, r.content)
        register_file(conn, doc_id, fmt, str(dest), sha256_file(dest),
                      len(r.content), url, "http")
        return doc_id, fmt, "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the batch
        return doc_id, fmt, f"error:{type(exc).__name__}:{exc}"


async def fetch_docs_async(conn: sqlite3.Connection, mirror_root: Path,
                           doc_ids: list[str], formats: list[str],
                           concurrency: int = 8,
                           force: bool = False) -> list[tuple[str, str, str]]:
    """Fetch requested formats for doc_ids, skipping ones already on disk."""
    todo: list[tuple[str, str]] = []
    for doc_id in doc_ids:
        for fmt in formats:
            if force or not _has_local(conn, doc_id, fmt):
                todo.append((doc_id, fmt))

    results: list[tuple[str, str, str]] = []
    if not todo:
        return results
    require_network(f"{todo[0][0]} ({todo[0][1]})" if len(todo) == 1 else
                    f"{len(todo)} document files ({todo[0][0]}, ...)")

    import httpx  # lazy: serving from an existing library never needs it
    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=httpx.Timeout(60.0),
        limits=limits,
    ) as client:
        tasks = [_fetch_one(client, sem, conn, mirror_root, d, f) for d, f in todo]
        done = 0
        for coro in asyncio.as_completed(tasks):
            results.append(await coro)
            done += 1
            if done % 250 == 0:
                conn.commit()  # incremental: crash-safe & resumable
    conn.commit()
    return results


def fetch_docs(conn: sqlite3.Connection, mirror_root: Path, doc_ids: list[str],
               formats: list[str], concurrency: int = 8,
               force: bool = False) -> list[tuple[str, str, str]]:
    """Sync wrapper around fetch_docs_async."""
    return asyncio.run(fetch_docs_async(conn, mirror_root, doc_ids, formats,
                                        concurrency=concurrency, force=force))


def fetch_doc_sync(conn: sqlite3.Connection, mirror_root: Path, doc_id: str,
                   fmt: str) -> tuple[str, str, str]:
    """On-demand single-document fetch (used by the MCP server)."""
    return fetch_docs(conn, mirror_root, [doc_id], [fmt])
