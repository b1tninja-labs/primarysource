"""The offline catalogue snapshot: what could be installed, answerable with no network.

`refresh()` is the only function here that touches the network (through `catalog`'s own `_get`, so the https-only
rule and the size limit apply). It pages through the English OPDS feed and writes `$ZIMLORE_HOME/catalog.json`
atomically. Everything else reads that file. A missing snapshot is an error naming
`primarysource zim catalog --refresh`; a
corrupt or wrong-schema one is also an error, never an empty snapshot, because "the catalogue has nothing called
flask" and "the snapshot could not be read" send an agent to opposite conclusions.

Facts measured against the live feed on 2026-11-07: `count=5000&lang=eng` returned all 1,309 entries in one 1.5 MB
document, but `count` is honoured as a page size and `start` as an offset (`itemsPerPage` and `startIndex` echo
them), so `refresh` pages in 500s rather than relying on one reply that a server may cap.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import catalog, library
from .errors import ZimloreError

SCHEMA = 1
FILE_NAME = "catalog.json"
PAGE_SIZE = 500
MAX_PAGES = 100
HINT = "primarysource zim catalog --refresh"
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_FIELDS = ("name", "title", "date", "language", "summary", "creator", "articles", "approx_bytes", "url", "tags")


def path() -> Path:
    return library.home() / FILE_NAME


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_dict(entry: catalog.CatalogEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "title": entry.title,
        "date": entry.date,
        "language": entry.language,
        "summary": entry.summary,
        "creator": entry.creator,
        "articles": entry.articles,
        "approx_bytes": entry.approx_bytes,
        "url": entry.url,
        "tags": list(entry.tags),
    }


def refresh(*, language: str = "eng", base: str = "", opener: catalog.Opener | None = None) -> dict[str, Any]:
    """Fetch the whole feed for `language` and replace the snapshot. Network. The old snapshot is untouched
    unless every page was read and at least one entry came back."""
    base = base or catalog.CATALOG_URL
    entries: list[catalog.CatalogEntry] = []
    total = 0
    start = 0
    pages = 0
    while pages < MAX_PAGES:
        params = {"count": str(PAGE_SIZE), "start": str(start)}
        if language:
            params["lang"] = language
        page, total = catalog.parse_feed(catalog._get(f"{base}?{urllib.parse.urlencode(params)}", opener))
        pages += 1
        entries.extend(e for e in page if _SAFE_NAME.fullmatch(e.name))
        start += PAGE_SIZE
        if start >= total:
            break
    else:
        raise ZimloreError(f"the catalogue still had entries after {MAX_PAGES} pages; not writing a snapshot")
    if not entries:
        raise ZimloreError(
            "the catalogue returned no ZIM entries; the existing snapshot (if any) was kept",
            "try again later, or check the language code",
        )
    fetched_at = _stamp(datetime.now(UTC))
    document = {
        "schema": SCHEMA,
        "fetched_at": fetched_at,
        "language": language,
        "total_results": total,
        "entries": [_entry_dict(e) for e in entries],
    }
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, target)
    return {
        "path": str(target),
        "entries": len(entries),
        "total_results": total,
        "pages": pages,
        "fetched_at": fetched_at,
        "bytes": target.stat().st_size,
    }


def _missing() -> ZimloreError:
    return ZimloreError(f"no catalogue snapshot at {path()}", HINT)


def _corrupt(why: str) -> ZimloreError:
    return ZimloreError(f"the catalogue snapshot {path()} cannot be used ({why})", HINT)


def _entry_from(raw: object) -> catalog.CatalogEntry:
    if not isinstance(raw, dict) or any(key not in raw for key in _FIELDS):
        raise ValueError("an entry lacks required fields")
    strings = ("name", "title", "date", "language", "summary", "creator", "url")
    ints = ("articles", "approx_bytes")
    if not all(isinstance(raw[k], str) for k in strings) or not all(
        isinstance(raw[k], int) and not isinstance(raw[k], bool) for k in ints
    ):
        raise ValueError("an entry has a field of the wrong type")
    tags = raw["tags"]
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ValueError("an entry has malformed tags")
    if not _SAFE_NAME.fullmatch(raw["name"]):
        raise ValueError(f"an entry has an unusable name {raw['name']!r}")
    return catalog.CatalogEntry(**{**{k: raw[k] for k in _FIELDS}, "tags": tuple(tags)})


def load(today: datetime | None = None) -> tuple[list[catalog.CatalogEntry], str, int]:
    """(entries, fetched_at, age_days). Offline. Raises `ZimloreError` (hint: `primarysource zim catalog
    --refresh`) when
    there is no snapshot or it cannot be used."""
    target = path()
    if not target.is_file():
        raise _missing()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise _corrupt(str(error)) from error
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise _corrupt(
            f"schema {raw.get('schema') if isinstance(raw, dict) else type(raw).__name__}, expected {SCHEMA}"
        )
    listed = raw.get("entries")
    fetched = raw.get("fetched_at")
    if not isinstance(listed, list) or not isinstance(fetched, str):
        raise _corrupt("no entries list or no fetched_at")
    try:
        when = datetime.strptime(fetched, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        entries = [_entry_from(item) for item in listed]
    except ValueError as error:
        raise _corrupt(str(error)) from error
    age = max(0, ((today or datetime.now(UTC)) - when).days)
    return entries, fetched, age


def available(
    query: str, limit: int = 8, installed: dict[str, str] | None = None, today: datetime | None = None
) -> dict[str, Any]:
    """Snapshot entries ranked against `query` with the same ranking as `library.rank` (exact beats all-words
    beats prefix beats substring beats fuzzy), newest edition of each name. Offline."""
    wanted = library.norm(query)
    if not wanted:
        raise ZimloreError("empty query", "give a few words, e.g. primarysource zim available flask")
    entries, fetched_at, age = load(today)
    have = installed or {}
    scored: list[tuple[float, str, catalog.CatalogEntry, str]] = []
    for entry in catalog.latest(entries):
        score, why = library.score_aliases(wanted, library.name_aliases(entry.name, entry.title))
        if score:
            scored.append((score, entry.name, entry, why))
    scored.sort(key=lambda item: (-item[0], item[1]))
    rows = [
        {
            "name": entry.name,
            "title": entry.title,
            "date": entry.date,
            "approx_mb": round(entry.approx_bytes / 1e6, 1),
            "articles": entry.articles,
            "install": f"primarysource zim get {entry.name}",
            "installed": entry.name in have,
            "installed_edition": have.get(entry.name),
            "match": why,
            "snapshot_age_days": age,
        }
        for _, _, entry, why in scored[: max(1, limit)]
    ]
    return {
        "query": query,
        "available": rows,
        "matches": len(scored),
        "snapshot": {"fetched_at": fetched_at, "age_days": age, "entries": len(entries), "offline": True},
    }
