"""Verified-errata overlay from the RFC Editor errata service.

Two sources. The primary one is the RFC Editor's published bulk API,
www.rfc-editor.org/api/v1/errata.json (every erratum, ~12 MB, one request;
robots.txt allows /api/): `sync_bulk` loads it so every document's errata
status is authoritative offline, including "none". The fallback is the
per-document errata.rfc-editor.org search page, fetched on demand only (that
host forbids crawling), parsed from its records presentation.
"""

from __future__ import annotations

import html as htmllib
import re
import sqlite3
import time
from datetime import datetime, timezone

import httpx

from .config import USER_AGENT, network_mode, require_network
from .sync.state import _now, get_meta, set_meta

ERRATA_URL = "https://errata.rfc-editor.org/search/?rfc_number={num}"
BULK_URL = "https://www.rfc-editor.org/api/v1/errata.json"
BULK_META = "errata_bulk_synced_at"

_RECORD_SPLIT = re.compile(r'Errata-ID:\s*<a href="/eid(\d+)/?"')
_TAG_RE = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return htmllib.unescape(_TAG_RE.sub("", fragment)).strip()


def _field(block: str, label: str) -> str | None:
    """Value of a <dt>label</dt><dd>value</dd> pair inside the metadata dl."""
    m = re.search(
        rf"<dt[^>]*>\s*{re.escape(label)}\s*</dt>\s*<dd[^>]*>(.*?)</dd>",
        block, re.S)
    return _text(m.group(1)) if m else None


def parse_errata(page: str) -> list[dict]:
    """Parse the errata service HTML (Full records view) into dicts."""
    parts = _RECORD_SPLIT.split(page)
    # parts[0] = preamble; then alternating eid, block
    out: list[dict] = []
    for eid, block in zip(parts[1::2], parts[2::2]):
        # Cut anything after the last record (page footer).
        block = block.split("Report New Erratum")[0]
        entry: dict = {"eid": int(eid),
                       "status": _field(block, "Status:") or "",
                       "type": _field(block, "Type:") or "",
                       "reported_by": _field(block, "Reported By:"),
                       "reported_date": _field(block, "Date Reported:"),
                       "section": None, "says": None,
                       "should_say": None, "notes": None,
                       "handler": None, "handler_date": None}
        if (v := _field(block, "Verified by:")):
            entry["handler"] = v
            entry["handler_date"] = _field(block, "Date Verified:")
        elif (v := _field(block, "Rejected by:")):
            entry["handler"] = v
            entry["handler_date"] = _field(block, "Date Rejected:")

        # "Section X says:" paragraph followed by a <pre> quote
        m = re.search(r"<p>\s*(?:Section\s+([^<]*?))?\s*says:\s*</p>\s*"
                      r"<pre[^>]*>(.*?)</pre>", block, re.S)
        if m:
            entry["section"] = (m.group(1) or "").strip().rstrip(":") or None
            entry["says"] = _text(m.group(2))
        m = re.search(r"<p>\s*It should say:\s*</p>\s*<pre[^>]*>(.*?)</pre>",
                      block, re.S)
        if m:
            entry["should_say"] = _text(m.group(1))
        m = re.search(r"<p>\s*Notes:\s*</p>\s*<pre[^>]*>(.*?)</pre>",
                      block, re.S)
        if m:
            entry["notes"] = _text(m.group(1))
        out.append(entry)
    return out


def fetch(rfc_number: int) -> str:
    """One polite request to the errata service; caller throttles."""
    with httpx.Client(headers={"User-Agent": USER_AGENT},
                      follow_redirects=True,
                      timeout=httpx.Timeout(30.0)) as client:
        r = client.get(ERRATA_URL.format(num=rfc_number))
        r.raise_for_status()
        return r.text


def store(conn: sqlite3.Connection, doc_id: str,
          entries: list[dict]) -> int:
    conn.execute("DELETE FROM errata WHERE doc_id=?", (doc_id,))
    rows = [(e["eid"], doc_id, e["status"], e.get("type"), e.get("section"),
             e.get("says"), e.get("should_say"), e.get("notes"),
             e.get("reported_by"), e.get("reported_date"),
             e.get("handler"), e.get("handler_date"), _now())
            for e in entries]
    conn.executemany(
        """INSERT OR REPLACE INTO errata(eid, doc_id, status, type, section,
               says, should_say, notes, reported_by, reported_date,
               handler, handler_date, fetched_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    return len(rows)


def sync_bulk(conn: sqlite3.Connection, data: list[dict] | None = None) -> dict:
    """Replace the errata table with the RFC Editor's bulk feed."""
    if data is None:
        require_network("the errata feed")
        with httpx.Client(headers={"User-Agent": USER_AGENT},
                          follow_redirects=True,
                          timeout=httpx.Timeout(120.0)) as client:
            r = client.get(BULK_URL)
            r.raise_for_status()
            data = r.json()
    now = _now()
    rows = []
    for e in data:
        doc = (e.get("doc-id") or "").upper().replace(" ", "")
        eid = str(e.get("errata_id") or "")
        if not doc or not eid.isdigit():
            continue
        rows.append((int(eid), doc, e.get("errata_status_code") or "",
                     e.get("errata_type_code"), e.get("section"),
                     e.get("orig_text"), e.get("correct_text"),
                     e.get("notes"), e.get("submitter_name"),
                     e.get("submit_date"), e.get("verifier_name"),
                     e.get("update_date"), now))
    conn.execute("DELETE FROM errata")
    conn.executemany(
        """INSERT OR REPLACE INTO errata(eid, doc_id, status, type, section,
               says, should_say, notes, reported_by, reported_date,
               handler, handler_date, fetched_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
    set_meta(conn, BULK_META, now)
    by = {}
    for r in conn.execute("SELECT status, COUNT(*) c FROM errata "
                          "GROUP BY status"):
        by[r["status"]] = r["c"]
    return {"errata": len(rows), "documents": conn.execute(
        "SELECT COUNT(DISTINCT doc_id) FROM errata").fetchone()[0],
            "by_status": by, "synced_at": now}


def bulk_synced_at(conn: sqlite3.Connection) -> str | None:
    return get_meta(conn, BULK_META)


def cached(conn: sqlite3.Connection, doc_id: str,
           status: str | None = None) -> list[dict]:
    q = "SELECT * FROM errata WHERE doc_id=?"
    args: list = [doc_id]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY eid"
    return [dict(r) for r in conn.execute(q, args)]


def refreshed_at(conn: sqlite3.Connection, doc_id: str) -> str | None:
    row = conn.execute(
        "SELECT MIN(fetched_at) t FROM errata WHERE doc_id=?",
        (doc_id,)).fetchone()
    return row["t"] if row and row["t"] else None


def ensure(conn: sqlite3.Connection, doc_id: str, refresh: bool = False,
           max_age_days: float = 7.0) -> dict:
    """Cached errata for doc_id, fetching from the service when absent
    (or when refresh=True / cache older than max_age_days)."""
    if not doc_id.startswith("RFC"):
        return {"doc_id": doc_id, "results": cached(conn, doc_id),
                "source": "cache",
                "note": "errata exist for RFC-series documents only"}
    # a bulk sync is authoritative for every document, including "none"
    fetched_at = refreshed_at(conn, doc_id) or bulk_synced_at(conn)
    fresh = False
    if fetched_at:
        try:
            t = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ")\
                 .replace(tzinfo=timezone.utc)
            fresh = ((datetime.now(timezone.utc) - t).total_seconds()
                     < max_age_days * 86400)
        except ValueError:
            fresh = False
    if fresh and not refresh:
        return {"doc_id": doc_id, "results": cached(conn, doc_id),
                "source": "cache", "fetched_at": fetched_at}
    if network_mode() == "offline":
        return {"doc_id": doc_id, "results": cached(conn, doc_id),
                "source": "cache (offline)", "fetched_at": fetched_at}
    time.sleep(0.25)  # politeness floor on the upstream service
    page = fetch(int(doc_id[3:]))
    store(conn, doc_id, parse_errata(page))
    return {"doc_id": doc_id, "results": cached(conn, doc_id),
            "source": "live", "fetched_at": refreshed_at(conn, doc_id)}