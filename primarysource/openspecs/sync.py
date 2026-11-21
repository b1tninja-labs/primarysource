"""Crawl the Open Specifications library and store each page for the index.

`fetch_catalog` walks `toc.json` from the root and writes `catalog.json`: every specification page, and no HTML.
It also records `SUPPLEMENTS`, Learn pages the tables of contents do not list. `sync_pages` downloads each
catalogued page, keeps its text, and adds the specification to the search index. A supplement is one HTML page
split into a section per chapter heading. A page already stored for the same URL is not downloaded again. A
guessed `toc.json` that is not there (HTTP 404) is recorded and skipped; the root table being missing is an error.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fetch import Fetcher
from primarysource.fsutil import atomic_write, sha256
from primarysource.index import index_document, open_write
from primarysource.model import Document, Section, Unit
from primarysource.openspecs.site import (
    DOC_ID,
    HOSTS,
    MAX_TOC_BYTES,
    ROOT_TOC,
    SUPPLEMENTS,
    Supplement,
    doc_id,
    pages_from_toc,
    section_id,
    toc_of,
)
from primarysource.readers.html import Document as HtmlDocument
from primarysource.readers.html import Heading, convert, to_plain

MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_TOCS = 5_000
MAX_PAGES = 1_000_000
CATALOG = "catalog.json"
CHECKPOINT = "crawl.json"
INDEX = "sections.sqlite"
REBUILD = "primarysource openspecs index"
FETCH = "primarysource openspecs fetch"
_ATTEMPTS = 5
_TRANSIENT = ("forcibly closed", "timed out", "Timeout", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503")


@dataclass(frozen=True, slots=True)
class Page:
    """One Learn page of one specification, as the catalog records it."""

    doc: str
    section: str
    title: str
    url: str
    depth: int

    def as_dict(self) -> dict[str, object]:
        return {
            "doc": self.doc,
            "section": self.section,
            "title": self.title,
            "url": self.url,
            "depth": self.depth,
        }


@dataclass(frozen=True, slots=True)
class FetchResult:
    path: Path
    documents: int
    pages: int
    tocs: int
    missing: int


@dataclass(frozen=True, slots=True)
class SyncResult:
    doc: str
    sections: int
    requests: int
    skipped: bool


def fetch_catalog(
    home: Path,
    *,
    transport: Callable[[str, int], bytes] | None = None,
    environ: Mapping[str, str] | None = None,
) -> FetchResult:
    """Walk every table of contents and write `catalog.json`. Page HTML is not downloaded.

    A dropped connection is retried. Progress is written to `crawl.json`, and a later fetch continues from it.
    """
    fetcher = Fetcher(HOSTS, transport, min_interval=0 if transport else 1.0, collection="openspecs", environ=environ)
    quick = transport is not None
    pages, titles, seen_url, used, seen_toc, queued, queue, missing = _resume(home)
    while queue:
        if len(seen_toc) >= MAX_TOCS:
            raise LibError(
                f"stopped after {MAX_TOCS} tables of contents",
                "the Open Specifications tree is smaller than that; the crawl is following a loop",
            )
        toc_url = queue.pop(0)
        if toc_url in seen_toc:
            continue
        body = _toc(fetcher, toc_url, required=toc_url == ROOT_TOC, quick=quick)
        if body is None:
            if toc_url not in missing:
                missing.append(toc_url)
        else:
            for url, title, depth in pages_from_toc(body, toc_url):
                child = toc_of(url)
                if child not in seen_toc and child not in queued:
                    queued.add(child)
                    queue.append(child)
                if url in seen_url:
                    continue
                spec = doc_id(url, title)
                if spec is None:
                    continue
                if len(pages) >= MAX_PAGES:
                    raise LibError(f"stopped after {MAX_PAGES} pages", "the catalog is larger than this crawl allows")
                seen_url.add(url)
                section = section_id(title, used.setdefault(spec, set()))
                used[spec].add(section)
                pages.append(Page(spec, section, title, url, depth))
                _prefer_title(titles, spec, title)
        seen_toc.add(toc_url)
        if len(seen_toc) % 25 == 0:
            print(f"openspecs fetch: {len(seen_toc)} tables, {len(pages)} pages", file=sys.stderr)
            _save_crawl(home, pages, titles, seen_url, used, seen_toc, queued, queue, missing)
    _add_supplements(pages, titles, seen_url)
    record = {
        "source": ROOT_TOC,
        "fetched": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "documents": titles,
        "missing_tocs": missing,
        "pages": [page.as_dict() for page in pages],
    }
    path = home / CATALOG
    atomic_write(path, (json.dumps(record, indent=2) + "\n").encode())
    (home / CHECKPOINT).unlink(missing_ok=True)
    return FetchResult(path, len(titles), len(pages), len(seen_toc) - len(missing), len(missing))


def sync_pages(
    home: Path,
    only: Sequence[str] | None = None,
    *,
    transport: Callable[[str, int], bytes] | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[SyncResult]:
    """Download catalogued pages that are not stored yet, and index each specification that changed."""
    catalog = load_catalog(home)
    wanted = _wanted(only)
    fetcher = Fetcher(HOSTS, transport, min_interval=0 if transport else 1.0, collection="openspecs", environ=environ)
    grouped = _grouped(catalog, wanted)
    if wanted is not None:
        unknown = wanted - set(grouped)
        if unknown:
            raise LibError(
                f"not in the catalog: {', '.join(sorted(unknown))}",
                "primarysource openspecs docs",
                FETCH,
            )
    titles = _titles(home)
    conn = open_write(home / INDEX, rebuild_command=REBUILD)
    results: list[SyncResult] = []
    try:
        for spec, pages in grouped.items():
            supplement = _supplement(spec)
            if supplement is not None:
                result = _sync_supplement(home, conn, supplement, pages, fetcher)
            else:
                result = _sync_spec(home, conn, spec, pages, titles, fetcher)
            results.append(result)
            print(f"openspecs sync: {spec} ({result.requests} request(s))", file=sys.stderr)
    finally:
        conn.close()
    return results


def load_catalog(home: Path) -> list[Page]:
    """The pages `fetch_catalog` wrote. A missing or unreadable catalog names `fetch`."""
    path = home / CATALOG
    if not path.is_file():
        raise LibError(f"no Open Specifications catalog in {home}", action=FETCH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LibError(f"{path} is not a readable catalog", action=FETCH) from exc
    raw = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise LibError(f"{path} has no pages", action=FETCH)
    pages: list[Page] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        page = _page(item)
        if page is not None:
            pages.append(page)
    return pages


def page_file(home: Path, doc: str, section: str) -> Path:
    """Where one page's text is stored. The names are the catalog's own ids, so a catalog cannot name a path."""
    if DOC_ID.fullmatch(doc) is None or not section or "/" in section or section in (".", ".."):
        raise LibError(f"not a stored page: {doc} {section}", "primarysource openspecs docs")
    return home / "pages" / doc / f"{section}.json"


def document_from(home: Path, doc: str, title: str, pages: Sequence[Page]) -> Document:
    """One specification: a section per stored page, in catalog order."""
    sections: list[Section] = []
    for page in pages:
        path = page_file(home, page.doc, page.section)
        if not path.is_file():
            continue
        stored = json.loads(path.read_text(encoding="utf-8"))
        blocks = stored.get("blocks") if isinstance(stored, dict) else None
        units = tuple(block for block in blocks if isinstance(block, str)) if isinstance(blocks, list) else ()
        sections.append(Section(page.section, page.title, units, page.depth))
    return Document(doc, title, Unit.BLOCK, tuple(sections))


def _add_supplements(pages: list[Page], titles: dict[str, str], seen_url: set[str]) -> None:
    """Record each supplement that the tables of contents did not already list."""
    for item in SUPPLEMENTS:
        if item.url in seen_url:
            continue
        if len(pages) >= MAX_PAGES:
            raise LibError(f"stopped after {MAX_PAGES} pages", "the catalog is larger than this crawl allows")
        seen_url.add(item.url)
        pages.append(Page(item.doc, section_id(item.title, ()), item.title, item.url, 1))
        _prefer_title(titles, item.doc, item.title)


def _grouped(catalog: Sequence[Page], wanted: set[str] | None) -> dict[str, list[Page]]:
    """Catalog pages selected by `wanted`, plus any supplement the catalog does not already name."""
    grouped: dict[str, list[Page]] = {}
    for page in catalog:
        if wanted is None or page.doc in wanted:
            grouped.setdefault(page.doc, []).append(page)
    for item in SUPPLEMENTS:
        if wanted is not None and item.doc not in wanted:
            continue
        grouped.setdefault(item.doc, []).append(Page(item.doc, section_id(item.title, ()), item.title, item.url, 1))
    return grouped


def _supplement(doc: str) -> Supplement | None:
    for item in SUPPLEMENTS:
        if item.doc == doc:
            return item
    return None


def _sync_spec(
    home: Path,
    conn: sqlite3.Connection,
    spec: str,
    pages: Sequence[Page],
    titles: Mapping[str, str],
    fetcher: Fetcher,
) -> SyncResult:
    requests = 0
    changed = False
    for page in pages:
        path = page_file(home, page.doc, page.section)
        if _stored(path, page.url):
            continue
        html = fetcher.get(page.url, MAX_HTML_BYTES)
        requests += 1
        _write_page(path, page, html)
        changed = True
    if changed or not _indexed(conn, spec):
        document = document_from(home, spec, titles.get(spec, spec), pages)
        index_document(conn, document)
        return SyncResult(spec, len(document.sections), requests, not changed)
    return SyncResult(spec, len(pages), 0, True)


def _sync_supplement(
    home: Path,
    conn: sqlite3.Connection,
    item: Supplement,
    pages: Sequence[Page],
    fetcher: Fetcher,
) -> SyncResult:
    """Download one Learn article and store a section per chapter heading."""
    if pages and all(_stored(page_file(home, page.doc, page.section), page.url) for page in pages):
        if not _indexed(conn, item.doc):
            document = document_from(home, item.doc, item.title, pages)
            index_document(conn, document)
            return SyncResult(item.doc, len(document.sections), 0, True)
        return SyncResult(item.doc, len(pages), 0, True)
    html = fetcher.get(item.url, MAX_HTML_BYTES)
    chapters = _chapters(item, html)
    digest = sha256(html)
    for page, blocks in chapters:
        record = {**page.as_dict(), "sha256": digest, "blocks": blocks}
        atomic_write(page_file(home, page.doc, page.section), (json.dumps(record) + "\n").encode())
    _drop_stale(home, item.doc, [page for page, _blocks in chapters])
    stored = [page for page, _blocks in chapters]
    _replace_catalog_doc(home, item, stored)
    document = document_from(home, item.doc, item.title, stored)
    index_document(conn, document)
    return SyncResult(item.doc, len(document.sections), 1, False)


def _chapters(item: Supplement, html: bytes) -> list[tuple[Page, list[str]]]:
    """One catalog page per chapter heading. A page with no headings stays one section."""
    converted = convert(html.decode("utf-8", errors="replace"), item.url)
    parts = _chapter_parts(converted, item.title)
    used: set[str] = set()
    chapters: list[tuple[Page, list[str]]] = []
    for title, depth, blocks in parts:
        section = section_id(title, used)
        used.add(section)
        chapters.append((Page(item.doc, section, title, item.url, depth), blocks))
    return chapters


def _chapter_parts(converted: HtmlDocument, fallback: str) -> list[tuple[str, int, list[str]]]:
    heads = [head for head in converted.headings if head.kind == "heading" and head.text.strip()]
    level = _chapter_level(heads)
    if level is None:
        return [(fallback, 1, [to_plain(block) for block in converted.blocks])]
    chosen = [head for head in heads if head.level == level]
    parts: list[tuple[str, int, list[str]]] = []
    if chosen[0].block > 0:
        parts.append((fallback, 1, [to_plain(block) for block in converted.blocks[: chosen[0].block]]))
    for head in chosen:
        start, end = converted.span(converted.headings.index(head))
        parts.append((head.text.strip(), head.level, [to_plain(block) for block in converted.blocks[start:end]]))
    return parts


def _chapter_level(heads: Sequence[Heading]) -> int | None:
    """The shallowest heading level that occurs more than once, else the only level, else none."""
    if not heads:
        return None
    counts: dict[int, int] = {}
    for head in heads:
        counts[head.level] = counts.get(head.level, 0) + 1
    repeated = [level for level in sorted(counts) if counts[level] >= 2]
    if repeated:
        return repeated[0]
    return min(counts)


def _drop_stale(home: Path, doc: str, pages: Sequence[Page]) -> None:
    directory = home / "pages" / doc
    if not directory.is_dir():
        return
    keep = {page_file(home, page.doc, page.section) for page in pages}
    for path in directory.glob("*.json"):
        if path not in keep:
            path.unlink()


def _replace_catalog_doc(home: Path, item: Supplement, pages: Sequence[Page]) -> None:
    """Replace this document's catalog rows. Other documents stay as they were."""
    path = home / CATALOG
    data = json.loads(path.read_text(encoding="utf-8"))
    documents = data.get("documents") if isinstance(data.get("documents"), dict) else {}
    documents[item.doc] = item.title
    data["documents"] = documents
    kept = [row for row in data.get("pages", []) if not (isinstance(row, dict) and row.get("doc") == item.doc)]
    data["pages"] = [*kept, *[page.as_dict() for page in pages]]
    atomic_write(path, (json.dumps(data) + "\n").encode())


def _resume(
    home: Path,
) -> tuple[list[Page], dict[str, str], set[str], dict[str, set[str]], set[str], set[str], list[str], list[str]]:
    """A crawl in progress, or a fresh one from the root table."""
    path = home / CHECKPOINT
    if not path.is_file():
        return [], {}, set(), {}, set(), {ROOT_TOC}, [ROOT_TOC], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], {}, set(), {}, set(), {ROOT_TOC}, [ROOT_TOC], []
    if not isinstance(data, dict):
        return [], {}, set(), {}, set(), {ROOT_TOC}, [ROOT_TOC], []
    pages = [page for item in data.get("pages", []) if isinstance(item, dict) and (page := _page(item))]
    raw_titles = data.get("documents")
    titles = {str(key): str(value) for key, value in raw_titles.items()} if isinstance(raw_titles, dict) else {}
    raw_used = data.get("used")
    used: dict[str, set[str]] = {}
    if isinstance(raw_used, dict):
        for doc, sections in raw_used.items():
            if isinstance(sections, list):
                used[str(doc)] = {section for section in sections if isinstance(section, str)}
    seen = _strings(data.get("seen_toc"))
    queue = _strings(data.get("queue"))
    # A crash can leave the table that was in progress marked done and its pages unstored, so a resume fetches
    # every table already seen as well as the ones still queued. Pages already recorded stay, and a repeated URL
    # does not become a second section.
    again = list(dict.fromkeys([*queue, *seen])) or [ROOT_TOC]
    return (
        pages,
        titles,
        set(_strings(data.get("seen_url"))),
        used,
        set(),
        set(again),
        again,
        [],
    )


def _save_crawl(
    home: Path,
    pages: list[Page],
    titles: dict[str, str],
    seen_url: set[str],
    used: dict[str, set[str]],
    seen_toc: set[str],
    queued: set[str],
    queue: list[str],
    missing: list[str],
) -> None:
    record = {
        "documents": titles,
        "pages": [page.as_dict() for page in pages],
        "seen_url": sorted(seen_url),
        "used": {doc: sorted(sections) for doc, sections in used.items()},
        "seen_toc": sorted(seen_toc),
        "queued": sorted(queued),
        "queue": queue,
        "missing": missing,
    }
    atomic_write(home / CHECKPOINT, (json.dumps(record) + "\n").encode())


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _toc(fetcher: Fetcher, url: str, *, required: bool, quick: bool) -> bytes | None:
    """The table, None when it is missing. A dropped connection is retried; a required table still raises."""
    for attempt in range(_ATTEMPTS):
        try:
            return fetcher.get(url, MAX_TOC_BYTES)
        except LibError as exc:
            if not required and "HTTP 404" in exc.message:
                return None
            transient = any(token in exc.message for token in _TRANSIENT)
            if transient and attempt + 1 < _ATTEMPTS:
                if not quick:
                    time.sleep(min(30, 2**attempt))
                continue
            if required:
                raise
            return None
    return None


def _prefer_title(titles: dict[str, str], doc: str, title: str) -> None:
    current = titles.get(doc)
    marked = f"[{doc}]" in title
    if current is None or (marked and (f"[{doc}]" not in current or len(title) < len(current))):
        titles[doc] = title


def _wanted(only: Sequence[str] | None) -> set[str] | None:
    if not only:
        return None
    found: set[str] = set()
    for token in only:
        doc = token.strip().upper().removeprefix("OPENSPECS:")
        if DOC_ID.fullmatch(doc) is None:
            raise LibError(f"not an Open Specifications id: {token!r}", "use an id such as MS-SMB2")
        found.add(doc)
    return found


def _titles(home: Path) -> dict[str, str]:
    path = home / CATALOG
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if DOC_ID.fullmatch(str(key))}


def _page(item: dict[str, object]) -> Page | None:
    doc, section, title, url, depth = (
        item.get("doc"),
        item.get("section"),
        item.get("title"),
        item.get("url"),
        item.get("depth"),
    )
    if not isinstance(doc, str) or not isinstance(section, str):
        return None
    if not isinstance(title, str) or not isinstance(url, str):
        return None
    if DOC_ID.fullmatch(doc) is None:
        return None
    return Page(doc, section, title, url, depth if isinstance(depth, int) else 1)


def _stored(path: Path, url: str) -> bool:
    if not path.is_file():
        return False
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(stored, dict) and stored.get("url") == url and isinstance(stored.get("blocks"), list)


def _write_page(path: Path, page: Page, html: bytes) -> None:
    text = html.decode("utf-8", errors="replace")
    converted = convert(text, page.url)
    blocks = [to_plain(block) for block in converted.blocks]
    record = {**page.as_dict(), "sha256": sha256(html), "blocks": blocks}
    atomic_write(path, (json.dumps(record) + "\n").encode())


def _indexed(conn: sqlite3.Connection, doc: str) -> bool:
    return conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc,)).fetchone() is not None
