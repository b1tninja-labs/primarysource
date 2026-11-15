"""Search and browse: `POST https://webstore-search-api.iec.ch/api/search`, the API the storefront's own list calls.

Observed in the capture: a JSON body (`mode`, `query`, `from`, `size`, `validOnly`, `sortBy`, `language`,
`dateRanges`, `terms`, `publicationIds`, `showTrf`, `collapsed`), no cookie and no credential, `access-control-
allow-origin: *` on the answer. Facets are the `terms` map: facet name, then level (`"1"`, ...), then the values.
Facet names seen in the answer: `header`, `committee`, `ics`, `type`, `publication_type`, `vap_type`,
`available_formats`, `status`.

Not observed, and so not implemented: a non-empty `query` (every captured search had `query: ""`), the
`dateRanges` value format, the `/api/publications/autocomplete` answer, and levels beyond `"1"` of a facet.
`SearchQuery.text` and `SearchQuery.date_ranges` pass through as the page's own JavaScript builds them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from primarysource.errors import LibError
from primarysource.iec.webstore.models import SearchPage, parse_search
from primarysource.iec.webstore.transport import HttpRequest, Transport

__all__ = ["MAX_PAGE_SIZE", "SEARCH_URL", "SearchClient", "SearchQuery", "facet_filter"]

SEARCH_URL = "https://webstore-search-api.iec.ch/api/search"
STORE_ORIGIN = "https://webstore.iec.ch"
MAX_PAGE_SIZE = 100
"""The page's own page-size menu stops at 100 (10, 25, 50, 100); the capture asked for 100 once."""


def facet_filter(name: str, values: Sequence[str], level: int = 1) -> dict[str, dict[str, list[str]]]:
    """`{name: {"<level>": [values]}}`, the shape of one entry of `terms`."""
    return {name: {str(level): list(values)}}


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str = ""
    language: str = "en"
    valid_only: bool = True
    show_trf: bool = False
    terms: Mapping[str, Mapping[str, Sequence[str]]] = field(default_factory=dict)
    date_ranges: Mapping[str, Any] = field(default_factory=dict)
    publication_ids: Sequence[int] | None = None
    collapsed: bool = True
    """`collapsed` is what the page sends in list mode: one hit per reference group, editions folded away."""

    def payload(self, start: int, size: int) -> dict[str, Any]:
        return {
            "mode": "FULL",
            "query": self.text,
            "from": start,
            "size": size,
            "validOnly": self.valid_only,
            "sortBy": [{"reference": "asc"}],
            "language": self.language,
            "dateRanges": dict(self.date_ranges),
            "terms": {
                name: {str(level): list(vals) for level, vals in levels.items()}
                for name, levels in self.terms.items()
            },
            "publicationIds": list(self.publication_ids) if self.publication_ids is not None else None,
            "showTrf": self.show_trf,
            "collapsed": self.collapsed,
        }

    def with_terms(self, **facets: Sequence[str]) -> SearchQuery:
        """A copy with level-1 filters added, e.g. `query.with_terms(committee=["TC 86"], type=["IS"])`."""
        merged: dict[str, Mapping[str, Sequence[str]]] = dict(self.terms)
        for name, values in facets.items():
            merged[name] = {"1": list(values)}
        return SearchQuery(
            self.text,
            self.language,
            self.valid_only,
            self.show_trf,
            merged,
            self.date_ranges,
            self.publication_ids,
            self.collapsed,
        )


class SearchClient:
    def __init__(self, transport: Transport, url: str = SEARCH_URL) -> None:
        self._transport = transport
        self._url = url

    def search(self, query: SearchQuery, *, start: int = 0, size: int = 25) -> SearchPage:
        if start < 0 or not 1 <= size <= MAX_PAGE_SIZE:
            raise LibError(
                f"start={start}, size={size} is outside what the store's own pages ask for",
                f"use start >= 0 and 1 <= size <= {MAX_PAGE_SIZE}",
            )
        request = HttpRequest(
            "POST",
            self._url,
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": STORE_ORIGIN,
                "Referer": f"{STORE_ORIGIN}/",
            },
            json.dumps(query.payload(start, size)).encode("utf-8"),
        )
        response = self._transport.send(request)
        if response.status != 200:
            raise LibError(
                f"the search API answered HTTP {response.status}", "try again later; do not retry in a loop"
            )
        return parse_search(response.json(), start)

    def pages(self, query: SearchQuery, *, max_pages: int, size: int = 100) -> Iterator[SearchPage]:
        """At most `max_pages` pages, in order. The bound is required: a catalogue walk is never unbounded."""
        if max_pages < 1:
            raise LibError("max_pages must be at least 1", "pass the number of pages you are willing to fetch")
        start: int | None = 0
        for _ in range(max_pages):
            if start is None:
                return
            page = self.search(query, start=start, size=size)
            yield page
            start = page.next_start
