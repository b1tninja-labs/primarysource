"""Fetch the Ecma index and import the editions this package already pins.

`fetch` downloads the standards index and, when that page links to it, the withdrawn list.
It writes `remote.json` under the ecma home. It does not download a PDF.

`sync` imports each pinned edition whose page still serves the pinned URL. An edition already
stored under that pin is skipped. A standard the index lists and the catalogue does not pin is
not downloaded: the pin is a sha256 checked before the PDF is parsed.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primarysource.ecma.catalogue import HOSTS, Catalogue
from primarysource.ecma.catalogue import catalogue as packaged_catalogue
from primarysource.ecma.importer import import_edition, read_record
from primarysource.ecma.site import INDEX_URL, Listing, PageEdition, parse_index, parse_standard
from primarysource.errors import LibError
from primarysource.fetch import Fetcher, Transport
from primarysource.home import atomic_write

REMOTE = "remote.json"
MAX_HTML = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchResult:
    path: Path
    standards: int
    withdrawn: int


@dataclass(frozen=True, slots=True)
class SyncResult:
    key: str
    skipped: bool
    pdf: Path
    requests: int


def _fetcher(transport: Transport | None) -> Fetcher:
    if transport is None:
        return Fetcher(HOSTS)
    return Fetcher(HOSTS, transport, min_interval=0)


def _decode(data: bytes, url: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeError as exc:
        raise LibError(f"{url} is not UTF-8", "the standards pages are HTML") from exc


def read_remote(home: Path) -> dict[str, Any]:
    path = home / REMOTE
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(f"no Ecma index in {home}", "run primarysource ecma fetch") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("listings"), list):
        raise LibError(f"{path} is not an Ecma index", "run primarysource ecma fetch again")
    return loaded


def _write_remote(home: Path, listings: Sequence[Listing]) -> FetchResult:
    home.mkdir(parents=True, exist_ok=True)
    path = home / REMOTE
    payload = {
        "collection": "ecma",
        "listings": [
            {
                "number": row.number,
                "title": row.title,
                "changed": row.changed,
                "page_url": row.page_url,
                "list": row.list_name,
            }
            for row in listings
        ],
    }
    atomic_write(path, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    standards = sum(1 for row in listings if row.list_name == "standards")
    withdrawn = sum(1 for row in listings if row.list_name == "withdrawn")
    return FetchResult(path, standards, withdrawn)


def fetch_index(home: Path, *, transport: Transport | None = None) -> FetchResult:
    """Download the index and the withdrawn list it links to. PDFs are not fetched."""
    fetcher = _fetcher(transport)
    raw = fetcher.get(INDEX_URL, MAX_HTML)
    current, withdrawn_url = parse_index(_decode(raw, INDEX_URL), "standards")
    rows: list[Listing] = list(current)
    if withdrawn_url is not None:
        extra, _ = parse_index(_decode(fetcher.get(withdrawn_url, MAX_HTML), withdrawn_url), "withdrawn")
        rows.extend(extra)
    return _write_remote(home, rows)


def _page_url(remote: dict[str, Any], number: str) -> str:
    rows = [row for row in remote["listings"] if isinstance(row, dict) and row.get("number") == number]
    if not rows:
        raise LibError(
            f"ECMA-{number} is not in the fetched index",
            "run primarysource ecma fetch again",
        )
    current = [row for row in rows if row.get("list") == "standards"]
    chosen = (current or rows)[0]
    page = chosen.get("page_url")
    if not isinstance(page, str):
        raise LibError(f"ECMA-{number}: the index has no page URL", "run primarysource ecma fetch again")
    return page


def _pinned_on_page(page: tuple[PageEdition, ...], edition: int, source_url: str, number: str) -> None:
    match = next((row for row in page if row.edition == edition), None)
    if match is None:
        raise LibError(
            f"ECMA-{number} edition {edition} is not on its page",
            "the catalogue pin is older than the page; do not import it",
        )
    if match.source_url != source_url:
        raise LibError(
            f"ECMA-{number} edition {edition} is no longer at the pinned URL",
            f"the page says {match.source_url}",
        )


def sync_pinned(
    home: Path,
    only: Sequence[str] | None = None,
    *,
    transport: Transport | None = None,
    cat: Catalogue | None = None,
) -> tuple[SyncResult, ...]:
    """Import every pinned edition whose page still serves that PDF. Already imported editions are skipped."""
    cat = cat or packaged_catalogue()
    remote = read_remote(home)
    numbers = list(only) if only else sorted({row.number for row in cat.editions}, key=int)
    if not numbers:
        raise LibError("the Ecma catalogue has no editions", "")
    fetcher = _fetcher(transport)
    results: list[SyncResult] = []
    for number in numbers:
        pinned = [row for row in cat.editions if row.number == number]
        if not pinned:
            known = ", ".join(f"{row.number}@{row.edition}" for row in cat.editions)
            raise LibError(f"no Ecma standard {number} in the catalogue", f"known: {known}")
        page_url = _page_url(remote, number)
        before = fetcher.requests
        page = parse_standard(_decode(fetcher.get(page_url, MAX_HTML), page_url), number)
        record = read_record(home)
        for edition in pinned:
            _pinned_on_page(page, edition.edition, edition.source_url, number)
            stored = record["editions"].get(edition.key, {})
            pdf = home / f"{edition.key}.pdf"
            if isinstance(stored, dict) and stored.get("sha256") == edition.sha256 and pdf.is_file():
                results.append(SyncResult(edition.key, True, pdf, fetcher.requests - before))
            else:
                imported = import_edition(home, number, edition.edition, cat=cat, fetcher=fetcher)
                results.append(SyncResult(imported.key, False, imported.pdf, fetcher.requests - before))
            before = fetcher.requests
    return tuple(results)
