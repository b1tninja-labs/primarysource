"""Download the Bluetooth specification catalog and the HTML book each row links.

The catalog page is www.bluetooth.com. Each specification page links an HTML book on the same host. A book
file that is not under that book's directory is not fetched. Nothing is unpacked to a second tree: the HTML
is stored as it was published.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from primarysource.bluetooth.book import Part, parts, sections
from primarysource.bluetooth.catalogue import LISTING, Spec, book_url, parse_listing
from primarysource.errors import LibError
from primarysource.fetch import Fetcher, Transport
from primarysource.fsutil import atomic_write
from primarysource.home import collection_home

CATALOG = "catalog.json"
BOOKS = "books"
EXTRACTED = "extracted"
INDEX = "index.sqlite"
MAX_PAGE = 2 * 1024 * 1024
MAX_BOOK = 32 * 1024 * 1024
HOSTS = ("www.bluetooth.com",)
SYNC = "primarysource bluetooth sync"


@dataclass(frozen=True, slots=True)
class SyncResult:
    doc: str
    sections: int
    skipped: bool
    note: str


def default_home() -> Path:
    return collection_home("bluetooth")


def read_catalog(home: Path) -> list[Spec]:
    path = home / CATALOG
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(f"no Bluetooth catalog in {home}", "", SYNC) from exc
    rows = loaded.get("specs") if isinstance(loaded, dict) else None
    if not isinstance(rows, list):
        raise LibError(f"{path} is not a Bluetooth catalog", "", SYNC)
    specs: list[Spec] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        specs.append(
            Spec(
                str(item.get("doc", "")),
                str(item.get("title", "")),
                str(item.get("version", "")),
                str(item.get("kind", "")),
                str(item.get("status", "")),
                str(item.get("page", "")),
            )
        )
    return [item for item in specs if item.doc]


def fetch_catalog(home: Path, *, transport: Transport | None = None) -> list[Spec]:
    """Download the catalog page and store its rows. Books are not fetched."""
    fetcher = _fetcher(transport)
    html = fetcher.get(LISTING, MAX_PAGE).decode("utf-8", "replace")
    specs = parse_listing(html)
    _write_catalog(home, specs)
    return specs


def sync_books(
    home: Path,
    only: Sequence[str] = (),
    *,
    transport: Transport | None = None,
) -> list[SyncResult]:
    """Download each catalogued book that is not stored yet and write its sections."""
    wanted = set(only)
    specs = (
        read_catalog(home)
        if (home / CATALOG).is_file() and transport is None
        else fetch_catalog(home, transport=transport)
    )
    if wanted:
        known = {item.doc for item in specs}
        missing = wanted - known
        if missing:
            raise LibError(f"not in the Bluetooth catalog: {sorted(missing)[0]}", "primarysource bluetooth docs")
    fetcher = _fetcher(transport)
    home.mkdir(parents=True, exist_ok=True)
    (home / EXTRACTED).mkdir(exist_ok=True)
    results: list[SyncResult] = []
    for spec in specs:
        if wanted and spec.doc not in wanted:
            continue
        try:
            results.append(_one(home, spec, fetcher))
        except LibError as exc:
            print(f"error {spec.doc}: {exc.message}", file=sys.stderr, flush=True)
            results.append(SyncResult(spec.doc, 0, False, exc.message))
    return results


def _one(home: Path, spec: Spec, fetcher: Fetcher) -> SyncResult:
    stored = home / EXTRACTED / f"{spec.doc}.json"
    if stored.is_file():
        print(f"skip {spec.doc}", file=sys.stderr, flush=True)
        return SyncResult(spec.doc, _section_count(stored), True, "")
    page = _get(fetcher, spec.page, MAX_PAGE).decode("utf-8", "replace")
    book = book_url(page, spec.page)
    if book is None:
        print(f"no-html {spec.doc}", file=sys.stderr, flush=True)
        return SyncResult(spec.doc, 0, False, "no html book")
    folder = home / BOOKS / spec.doc
    index_html = _file(folder, "index-en.html")
    if index_html is None:
        index_html = _get(fetcher, book, MAX_BOOK).decode("utf-8", "replace")
        atomic_write(_place(folder, "index-en.html"), index_html.encode("utf-8"))
    plan = parts(index_html, book)
    files: list[tuple[Part, str]] = []
    for part in plan:
        text = _file(folder, part.path)
        if text is None:
            text = _get(fetcher, part.url, MAX_BOOK).decode("utf-8", "replace")
            atomic_write(_place(folder, part.path), text.encode("utf-8"))
        files.append((part, text))
    built = sections(files)
    payload = {
        "doc": spec.doc,
        "title": spec.title,
        "version": spec.version,
        "kind": spec.kind,
        "status": spec.status,
        "page": spec.page,
        "book": book,
        "sections": built,
    }
    atomic_write(stored, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
    print(f"imported {spec.doc} {len(built)}", file=sys.stderr, flush=True)
    return SyncResult(spec.doc, len(built), False, "")


def _get(fetcher: Fetcher, url: str, limit: int) -> bytes:
    """Fetch `url`, retrying when the host drops the connection."""
    last: LibError | None = None
    for attempt in range(4):
        try:
            return fetcher.get(url, limit)
        except LibError as exc:
            last = exc
            if "urlopen error" not in exc.message:
                raise
            print(f"retry {attempt + 1} {url}", file=sys.stderr, flush=True)
            time.sleep(2 * (attempt + 1))
    if last is None:
        raise LibError(f"could not fetch {url}", "retry the same sync")
    raise last


def _file(folder: Path, relative: str) -> str | None:
    """The text of a book file already on disk, or None when it still has to be downloaded."""
    path = folder.joinpath(*relative.split("/"))
    if not path.is_file() or path.stat().st_size == 0:
        return None
    return path.read_text(encoding="utf-8")


def _place(folder: Path, relative: str) -> Path:
    destination = folder.joinpath(*relative.split("/"))
    if not destination.resolve().is_relative_to(folder.resolve()):
        raise LibError(f"{relative} escapes the book directory", "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination


def _section_count(path: Path) -> int:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    found = loaded.get("sections") if isinstance(loaded, dict) else None
    return len(found) if isinstance(found, list) else 0


def _write_catalog(home: Path, specs: Sequence[Spec]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    payload = {
        "collection": "bluetooth",
        "source": LISTING,
        "specs": [
            {
                "doc": item.doc,
                "title": item.title,
                "version": item.version,
                "kind": item.kind,
                "status": item.status,
                "page": item.page,
            }
            for item in specs
        ],
    }
    atomic_write(home / CATALOG, (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def _fetcher(transport: Transport | None) -> Fetcher:
    if transport is None:
        return Fetcher(HOSTS, collection="bluetooth")
    return Fetcher(HOSTS, transport, min_interval=0, collection="bluetooth")
