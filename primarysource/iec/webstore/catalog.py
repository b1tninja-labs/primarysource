"""The local catalogue: one JSON stub per publication and an FTS5 index over them. Metadata only.

Layout, under `collection_home("iec")` (`$PRIMARYSOURCE_IEC_HOME`, else `$PRIMARYSOURCE_HOME/iec`, else the per-user
directory), never under a repository:

    <home>/webstore/stubs/<publication id>.json     designation, title, edition, status, price, categories, formats
    <home>/webstore/catalog.sqlite                  the core index (primarysource/index.py), one document per stub

The index holds the designation, title, edition, status, publication type, price (`free` is a word in it), the
technical committee, ICS codes and their titles, formats and languages. It holds no standard's text. The store's
catalogue abstract (the public blurb, owner decision 2026-11-14) is kept in stubs and index; pass
`include_abstract=False` to leave it out.

A sync is opt-in (`opt_in=True`), bounded (`max_pages`, at most `HARD_MAX_PAGES`), and as slow as the transport
makes it (the polite transport waits a second between requests and honours `primarysource.settings`). IEC's terms
on automated access were not in the capture and are unverified; see docs/iec-webstore.md before running one.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, bulk_lock
from primarysource.home import collection_home
from primarysource.iec.webstore.models import Publication
from primarysource.iec.webstore.search import SearchClient, SearchQuery
from primarysource.model import Document, Section, Unit
from primarysource.settings import require_network

__all__ = [
    "HARD_MAX_PAGES",
    "REBUILD_COMMAND",
    "CatalogHit",
    "catalog_home",
    "filter_catalog",
    "find",
    "load_stub",
    "rebuild_index",
    "stub_for",
    "sync_catalog",
    "write_stubs",
]

HARD_MAX_PAGES = 20
REBUILD_COMMAND = "python -m primarysource.iec.webstore index"
INDEX_NAME = "catalog.sqlite"


def catalog_home(home: Path | None = None) -> Path:
    """`<collection home>/webstore`; nothing is created."""
    return (home if home is not None else collection_home("iec")) / "webstore"


def _stubs(home: Path) -> Path:
    return home / "stubs"


def stub_for(publication: Publication, *, include_abstract: bool = True) -> dict[str, Any]:
    stub: dict[str, Any] = {
        "id": publication.id,
        "reference": publication.reference,
        "title": publication.title,
        "edition": publication.edition,
        "status": publication.status,
        "publication_type": publication.publication_type,
        "publication_date": publication.publication_date,
        "head": publication.head,
        "price": {"amount": publication.price.amount, "currency": publication.price.currency}
        if publication.price
        else None,
        "is_free": publication.is_free,
        "committee": {
            "level_1": publication.committee.level_1,
            "level_1_name": publication.committee.level_1_name,
            "level_2": publication.committee.level_2,
            "level_2_name": publication.committee.level_2_name,
        }
        if publication.committee
        else None,
        "ics": [{"code": i.code, "title": i.title, "group": i.level_1_title} for i in publication.ics],
        "formats": list(publication.formats),
        "languages": list(publication.languages),
        "files": [{"format": f.format, "language": f.language, "kind": f.kind} for f in publication.files],
        "pages": publication.pages,
        "isbn": publication.isbn,
        "urn": publication.urn,
        "lifecycle": [
            {
                "reference": item.reference,
                "edition": item.edition,
                "status": item.status,
                "date": item.publication_date,
            }
            for item in publication.lifecycle
        ],
        "url": publication.page_url,
        "fetched": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if include_abstract and publication.abstract:
        stub["abstract"] = publication.abstract
    return stub


def write_stubs(home: Path, publications: Iterable[Publication], *, include_abstract: bool = True) -> int:
    """Write one stub per publication, atomically; returns how many."""
    folder = _stubs(home)
    count = 0
    for publication in publications:
        data = json.dumps(stub_for(publication, include_abstract=include_abstract), indent=1, ensure_ascii=False)
        atomic_write(folder / f"{publication.id}.json", (data + "\n").encode("utf-8"))
        count += 1
    return count


def load_stub(home: Path, publication_id: int | str) -> dict[str, Any] | None:
    path = _stubs(home) / f"{int(publication_id)}.json"
    if not path.is_file():
        return None
    loaded = json.loads(path.read_text("utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _units(stub: dict[str, Any]) -> dict[str, list[str]]:
    price = stub.get("price")
    committee = stub.get("committee") or {}
    price_line = f"{price['currency']} {price['amount']:g}" if price else "no price listed"
    return {
        "Catalogue entry": [
            f"{stub['reference']}",
            f"{stub.get('title', '')}",
            f"edition {stub.get('edition', '')}",
            f"status {stub.get('status', '')}",
            f"type {stub.get('publication_type', '')}",
            f"published {stub.get('publication_date', '')}",
            *([f"abstract {stub['abstract']}"] if stub.get("abstract") else []),
        ],
        "Price": [f"price {price_line}", "free of charge, no cost" if stub.get("is_free") else "priced"],
        "Committee": [
            f"committee {committee.get('level_1', '')} {committee.get('level_1_name', '')}",
            f"subcommittee {committee.get('level_2', '')} {committee.get('level_2_name', '')}",
        ]
        if committee
        else [],
        "ICS": [f"ICS {i['code']} {i.get('title', '')} {i.get('group', '')}" for i in stub.get("ics", [])],
        "Formats": [
            f"formats {' '.join(stub.get('formats', []))}",
            f"languages {' '.join(stub.get('languages', []))}",
            f"head {stub.get('head', '')}",
        ],
    }


def _documents(home: Path) -> Iterator[Document]:
    for path in sorted(_stubs(home).glob("*.json")):
        stub = json.loads(path.read_text("utf-8"))
        sections = tuple(
            Section(title.lower().replace(" ", "-"), title, tuple(u for u in units if u.strip()))
            for title, units in _units(stub).items()
            if units
        )
        yield Document(str(stub["id"]), f"{stub['reference']} {stub.get('title', '')}".strip(), Unit.BLOCK, sections)


def rebuild_index(home: Path) -> int:
    """Rebuild `catalog.sqlite` from the stubs, atomically; returns the number of sections written."""
    if not _stubs(home).is_dir():
        raise LibError(f"no catalogue stubs under {home}", "run a sync first, or write stubs from a search")
    return index.rebuild(home / INDEX_NAME, _documents(home), rebuild_command=REBUILD_COMMAND)


def _category_values(stub: dict[str, Any]) -> list[str]:
    committee = stub.get("committee") or {}
    values = [committee.get("level_1", ""), committee.get("level_2", ""), stub.get("publication_type", "")]
    values += [stub.get("head", "")] + [i.get("code", "") for i in stub.get("ics", [])]
    return [v for v in values if v]


def filter_catalog(
    home: Path,
    *,
    free_only: bool = False,
    min_price: float | None = None,
    max_price: float | None = None,
    category_prefix: str | None = None,
    status: str | None = None,
    currency: str | None = None,
) -> list[dict[str, Any]]:
    """Stubs matching every given condition, ordered by designation. Reads the stubs only (no network).

    `category_prefix` is matched case-insensitively against the committee (`TC 86`, `SC 86A`), the ICS codes
    (`33.100` matches `33.100.10`), the publication type and the reference head. A stub with no price never matches
    a price bound or `free_only`.
    """
    folder = _stubs(home)
    if not folder.is_dir():
        raise LibError(f"no catalogue stubs under {home}", "run a sync first")
    prefix = category_prefix.casefold() if category_prefix else None
    found: list[dict[str, Any]] = []
    for path in folder.glob("*.json"):
        stub = json.loads(path.read_text("utf-8"))
        price = stub.get("price")
        amount = price["amount"] if price else None
        if free_only and not stub.get("is_free"):
            continue
        bounded = min_price is not None or max_price is not None
        if bounded and amount is None:
            continue
        if amount is not None and (
            (min_price is not None and amount < min_price) or (max_price is not None and amount > max_price)
        ):
            continue
        if currency and price and price.get("currency") != currency:
            continue
        if status and stub.get("status", "").casefold() != status.casefold():
            continue
        if prefix and not any(v.casefold().startswith(prefix) for v in _category_values(stub)):
            continue
        found.append(stub)
    return sorted(found, key=lambda s: s.get("reference", ""))


@dataclass(frozen=True, slots=True)
class CatalogHit:
    id: int
    reference: str
    title: str
    section: str
    snippet: str
    stub: dict[str, Any] | None


def find(
    home: Path, query: str, *, limit: int = 8, start: int = 0
) -> tuple[tuple[CatalogHit, ...], bool, int | None]:
    """Search the local catalogue. Returns `(hits, relaxed, next_start)`; no hits means nothing matched."""
    conn = index.open_read(home / INDEX_NAME, rebuild_command=REBUILD_COMMAND)
    try:
        result = index.search(conn, query, limit=limit, start=start)
    finally:
        conn.close()
    hits: list[CatalogHit] = []
    for h in result.hits:
        stub = load_stub(home, h.doc_id)
        reference = str((stub or {}).get("reference") or h.doc_title)
        hits.append(CatalogHit(int(h.doc_id), reference, h.doc_title, h.section_id, h.snippet, stub))
    return tuple(hits), result.relaxed, result.next_start


def sync_catalog(
    client: SearchClient,
    home: Path,
    query: SearchQuery,
    *,
    opt_in: bool = False,
    max_pages: int = 1,
    page_size: int = 100,
    include_abstract: bool = True,
) -> tuple[int, int]:
    """Walk up to `max_pages` pages of `query`, write the stubs, rebuild the index. Returns `(stubs, total)`.

    Refuses unless `opt_in` is true, refuses a bound above `HARD_MAX_PAGES`, and refuses when the settings forbid
    the network. Run it for a filtered slice (a committee, a publication type), not the whole 17 000 entries.
    """
    if not opt_in:
        raise LibError(
            "a catalogue sync is opt-in",
            "pass opt_in=True (CLI: --i-have-read-the-terms) after reading docs/iec-webstore.md section 'Terms'",
        )
    if not 1 <= max_pages <= HARD_MAX_PAGES:
        raise LibError(f"max_pages must be 1..{HARD_MAX_PAGES}", "sync a filtered slice, in several runs")
    require_network("the IEC catalogue", collection="iec")
    home.mkdir(parents=True, exist_ok=True)
    written = 0
    total = 0
    with bulk_lock(home, "sync"):
        for page in client.pages(query, max_pages=max_pages, size=page_size):
            total = page.total
            written += write_stubs(home, page.hits, include_abstract=include_abstract)
        if written:
            rebuild_index(home)
    return written, total
