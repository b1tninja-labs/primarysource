"""An opt-in, bounded catalog sync.

ISO's terms forbid harvesting the browsing platform and text-and-data-mining the no-cost content (docs/iso.md
section 3). This does neither: it asks the catalog search, which the public pages use, for metadata only, a few
queries and a few pages each, one request a second, and it stops at the first hard failure. It will not run
unless the caller passes `opt_in=True`, and the command line asks for that explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from primarysource.errors import LibError
from primarysource.iso.webstore.catalog import CatalogStore
from primarysource.iso.webstore.search import HARD_MAX_PAGES, CatalogSearch

MAX_QUERIES = 25
OPT_IN_HINT = "pass opt_in=True (command line: --i-accept-the-terms) after reading docs/iso-webstore.md section 7"


@dataclass(frozen=True, slots=True)
class SyncReport:
    queries: int
    requests: int
    written: int


def sync_catalog(
    search: CatalogSearch,
    store: CatalogStore,
    queries: Sequence[str],
    *,
    opt_in: bool = False,
    max_pages: int = 2,
    hits_per_page: int = 20,
    category: str | None = None,
) -> SyncReport:
    """Search each query for up to `max_pages` pages and write a stub per hit. Does not rebuild the index.

    Bounded: at most `MAX_QUERIES` queries and `HARD_MAX_PAGES` pages each. The session spaces the requests and
    honours `PRIMARYSOURCE_ISO_NETWORK` / `PRIMARYSOURCE_NETWORK` (offline stops it before the first request).
    """
    if not opt_in:
        raise LibError("a catalog sync is opt-in", OPT_IN_HINT)
    if not queries:
        raise LibError("nothing to sync", "give at least one search term")
    if len(queries) > MAX_QUERIES or not 1 <= max_pages <= HARD_MAX_PAGES:
        raise LibError(
            f"too much: at most {MAX_QUERIES} queries and {HARD_MAX_PAGES} pages each", "split it over several runs"
        )
    requests = written = 0
    for query in queries:
        for page in search.pages(query, category=category, max_pages=max_pages, hits_per_page=hits_per_page):
            requests += 1
            written += store.write_all(hit for hit in page.hits if hit.designation or hit.title)
    return SyncReport(len(queries), requests, written)
