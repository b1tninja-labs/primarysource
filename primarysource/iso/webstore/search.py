"""Catalog search: the site search the public pages embed.

What the capture shows: the store page (`/store.html`) loads the Algolia InstantSearch libraries and carries an
inline `algolia = { settings: { appID, apiKey, index: { name } } }` block. The search key in it is a *secured* key
(a base64 string that spells out `validUntil` and `restrictIndices`), valid for a day or so and limited to the
site's own indexes. The capture holds no request to the search service, so the request below is the service's
documented REST shape, not an observed one (docs/iso-webstore.md section 5 says so).

The key is read from the page at run time, held in a `Secret`, and never stored.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from primarysource.errors import LibError
from primarysource.iso.webstore.models import STATUS_KEYS, CatalogEntry
from primarysource.iso.webstore.secret import Secret
from primarysource.iso.webstore.session import BASE, WebstoreSession

STORE_PAGE = f"{BASE}/store.html"
CATEGORIES = ("standard", "page", "news", "publication", "event", "sdg", "organization", "committee", "ics", "member")
"""The `category` values the front end's label function handles."""
MAX_HITS_PER_PAGE = 50
HARD_MAX_PAGES = 20
"""The site's own pagination widget stops at 20 pages; so does this client."""

_BLOCK = re.compile(r"algolia\s*=\s*\{(.{0,2000}?)autocompleteDebounceTime", re.DOTALL)
_APP = re.compile(r"appID\s*:\s*'([A-Za-z0-9]{6,16})'")
_KEY = re.compile(r"apiKey\s*:\s*'([A-Za-z0-9+/=_-]{16,512})'")
_INDEX = re.compile(r"index\s*:\s*\{\s*name\s*:\s*'([A-Za-z0-9_.-]{1,80})'")


@dataclass(frozen=True, slots=True)
class SearchConfig:
    app_id: str
    api_key: Secret
    index: str

    @property
    def host(self) -> str:
        return f"{self.app_id.lower()}-dsn.algolia.net"

    def expires(self) -> datetime | None:
        """When the secured key stops working, if it says (`validUntil=<unix seconds>` inside the base64)."""
        try:
            decoded = base64.b64decode(self.api_key.reveal() + "=" * (-len(self.api_key.reveal()) % 4)).decode(
                "latin-1"
            )
        except (binascii.Error, ValueError):
            return None
        match = re.search(r"validUntil=(\d{9,11})", decoded)
        return datetime.fromtimestamp(int(match[1]), UTC) if match else None


def parse_config(page: str) -> SearchConfig:
    """The search settings out of the store page's inline script, or a `LibError` that says what was missing."""
    block = _BLOCK.search(page)
    scope = block[1] if block else ""
    app, key, index = _APP.search(scope), _KEY.search(scope), _INDEX.search(scope)
    if not (app and key and index):
        raise LibError(
            "the store page has no search settings block",
            "the site changed its search embedding; update primarysource.iso.webstore.search.parse_config",
        )
    return SearchConfig(app[1], Secret(key[1]), index[1])


def _strings(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return (str(value),) if isinstance(value, str) else tuple(str(x) for x in value)


def parse_hit(hit: dict[str, Any]) -> CatalogEntry:
    """A hit as a `CatalogEntry`. Only the attributes the front end reads are used (`reference`, `title`, `text`,
    `category`, `statusKey`, `seoURL`, `path`, `thumbnail`); `ics`, `committee`, `edition` and `year` are taken if a
    hit carries them, which the capture cannot confirm."""
    path = str(hit.get("seoURL") or "").strip()
    link = urllib.parse.urljoin(BASE + "/", path) if path else ""
    status_key = str(hit.get("statusKey") or "")
    ics = hit.get("ics") or ()
    toc = _strings(hit.get("toc"))
    return CatalogEntry(
        kind=str(hit.get("category") or ""),
        designation=str(hit.get("reference") or "").strip(),
        title=str(hit.get("title") or "").strip(),
        url=link,
        status=STATUS_KEYS.get(status_key, ""),
        status_key=status_key,
        edition=str(hit.get("edition") or ""),
        year=str(hit.get("year") or ""),
        ics=tuple(str(code) for code in ([ics] if isinstance(ics, str) else ics)),
        committee=str(hit.get("committee") or ""),
        language=str(hit.get("language") or ""),
        pages=int(hit["pages"]) if str(hit.get("pages") or "").isdigit() else None,
        published=str(hit.get("publicationDate") or hit.get("published") or ""),
        supersedes=_strings(hit.get("supersedes")),
        superseded_by=_strings(hit.get("supersededBy")),
        formats=_strings(hit.get("formats")),
        abstract=str(hit.get("text") or "").strip(),
        toc=toc,
        extra={k: v for k, v in hit.items() if k in ("facet", "order", "thumbnail", "path")},
    )


@dataclass(frozen=True, slots=True)
class SearchPage:
    hits: tuple[CatalogEntry, ...]
    total: int
    page: int
    pages: int

    @property
    def has_more(self) -> bool:
        return self.page + 1 < self.pages


class CatalogSearch:
    """Searches the site's catalog. One request per call; the session spaces them."""

    def __init__(
        self,
        session: WebstoreSession,
        config: SearchConfig | None = None,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session = session
        self._config = config
        self._now = now

    def config(self) -> SearchConfig:
        """The settings, read from the store page on first use and again once the key has expired."""
        current = self._config
        if current is not None:
            expiry = current.expires()
            if expiry is None or expiry > self._now():
                return current
        page = self._session.request("GET", STORE_PAGE)
        if page.status != 200:
            raise LibError(f"the store page: HTTP {page.status}", "retry later")
        self._config = parse_config(page.text())
        return self._config

    def search(
        self, query: str, *, category: str | None = None, page: int = 0, hits_per_page: int = 20
    ) -> SearchPage:
        """One page of hits for `query`, filtered here to `category` when given.

        An empty query is refused: the site's own front end sends none either (it answers locally, because each
        request is billed). The category filter is applied to the hits after the fact, because the capture does not
        show which attributes the service facets on.
        """
        if not query.strip():
            raise LibError("an empty search", "give at least one word")
        if category is not None and category not in CATEGORIES:
            raise LibError(f"unknown category {category!r}", f"one of: {', '.join(CATEGORIES)}")
        if not 0 <= page < HARD_MAX_PAGES or not 1 <= hits_per_page <= MAX_HITS_PER_PAGE:
            raise LibError(
                "page or page size out of bounds",
                f"page 0..{HARD_MAX_PAGES - 1}, 1..{MAX_HITS_PER_PAGE} hits per page",
            )
        config = self.config()
        params = urllib.parse.urlencode({"query": query.strip(), "page": page, "hitsPerPage": hits_per_page})
        body = json.dumps({"requests": [{"indexName": config.index, "params": params}]}).encode("utf-8")
        response = self._session.request(
            "POST",
            f"https://{config.host}/1/indexes/*/queries",
            headers={
                "X-Algolia-Application-Id": config.app_id,
                "X-Algolia-API-Key": config.api_key.reveal(),
                "Content-Type": "text/plain",
            },
            body=body,
            follow=False,
        )
        if response.status != 200:
            raise LibError(f"the search service: HTTP {response.status}", "retry later; the key may have expired")
        try:
            result = json.loads(response.body)["results"][0]
            hits = [parse_hit(hit) for hit in result["hits"] if isinstance(hit, dict)]
            total, number, pages = int(result["nbHits"]), int(result["page"]), int(result["nbPages"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LibError("the search service answered in an unknown shape", "update parse_hit") from exc
        if category is not None:
            hits = [hit for hit in hits if hit.kind == category]
        return SearchPage(tuple(hits), total, number, pages)

    def pages(
        self, query: str, *, category: str | None = None, max_pages: int = 3, hits_per_page: int = 20
    ) -> Sequence[SearchPage]:
        """Up to `max_pages` pages of one query, stopping early at the last page."""
        if not 1 <= max_pages <= HARD_MAX_PAGES:
            raise LibError(f"max_pages {max_pages} is out of bounds", f"use 1..{HARD_MAX_PAGES}")
        found: list[SearchPage] = []
        for number in range(max_pages):
            result = self.search(query, category=category, page=number, hits_per_page=hits_per_page)
            found.append(result)
            if not result.has_more:
                break
        return found
