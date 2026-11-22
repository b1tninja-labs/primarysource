"""The catalog as local stubs and a searchable index, with no document text.

Layout, under the collection home (`primarysource.home.collection_home("iso")`, never the repository):

```
<home>/webstore/catalog/<key>.json     one stub per catalog record (CatalogEntry.to_json)
<home>/webstore/catalog.sqlite         the core FTS5 index over the stubs, plus a `catalog_meta` table
```

The index reuses `primarysource.index` (BM25, porter stemming) with one section per record that spells out the
record's metadata as text (`price: 227.00 CHF`, `free`, `ics: 35.100`, `status: active`), so a metadata question is a
keyword search. `catalog_meta` carries the same facts as columns, for the filters a keyword cannot express.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write
from primarysource.home import collection_home
from primarysource.iso.webstore.auth import ensure_outside_repo
from primarysource.iso.webstore.models import CatalogEntry
from primarysource.model import Document, Section, Unit

REBUILD = "python -m primarysource.iso.webstore index"
_META = (
    "CREATE TABLE IF NOT EXISTS catalog_meta("
    "doc_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, free INTEGER, "
    "amount TEXT, currency TEXT NOT NULL, committee TEXT NOT NULL, ics TEXT NOT NULL)"
)


def default_root() -> Path:
    return collection_home("iso") / "webstore"


def as_document(entry: CatalogEntry) -> Document:
    """The record as an indexable document: one section whose units are `name: value` lines."""
    lines = [f"designation: {entry.designation}", f"title: {entry.title}", f"category: {entry.kind}"]
    if entry.status:
        lines.append(f"status: {entry.status}")
    if entry.edition or entry.year:
        lines.append(f"edition: {entry.edition} {entry.year}".strip())
    if entry.price is not None:
        lines.append("price: free" if entry.price.is_free else f"price: {entry.price}")
    lines.extend(f"ics: {code}" for code in entry.ics)
    if entry.committee:
        lines.append(f"committee: {entry.committee}")
    if entry.language:
        lines.append(f"language: {entry.language}")
    if entry.pages is not None:
        lines.append(f"pages: {entry.pages}")
    if entry.published:
        lines.append(f"published: {entry.published}")
    lines.extend(f"supersedes: {x}" for x in entry.supersedes)
    lines.extend(f"superseded by: {x}" for x in entry.superseded_by)
    if entry.formats:
        lines.append("formats: " + ", ".join(entry.formats))
    if entry.product_code:
        lines.append(f"product: {entry.product_code}")
    if entry.abstract:
        lines.append(f"abstract: {entry.abstract}")
    lines.extend(f"contents: {line}" for line in entry.toc)
    title = f"{entry.designation} {entry.title}".strip() or entry.key
    return Document(entry.key, title, Unit.BLOCK, (Section("metadata", "metadata", tuple(lines)),))


@dataclass(frozen=True, slots=True)
class CatalogFilter:
    """Filters over stored records. Every given condition must hold; an unknown fact never matches a condition on it.

    `min_price`/`max_price` apply to priced records only (a record with no price is not "cheap"); `free` is True for
    price zero, False for a price above zero. `ics_prefix` and `committee_prefix` match the start of any ICS code or
    of the committee name (`35.100`, `ISO/IEC JTC 1`).
    """

    category: str | None = None
    status: str | None = None
    free: bool | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    ics_prefix: str | None = None
    committee_prefix: str | None = None
    language: str | None = None

    def matches(self, entry: CatalogEntry) -> bool:
        if self.category is not None and entry.kind != self.category:
            return False
        if self.status is not None and entry.status != self.status:
            return False
        if self.language is not None and entry.language != self.language:
            return False
        if self.free is not None and entry.is_free != self.free:
            return False
        if self.min_price is not None or self.max_price is not None:
            if entry.price is None:
                return False
            if self.min_price is not None and entry.price.amount < self.min_price:
                return False
            if self.max_price is not None and entry.price.amount > self.max_price:
                return False
        if self.ics_prefix is not None and not any(code.startswith(self.ics_prefix) for code in entry.ics):
            return False
        return self.committee_prefix is None or entry.committee.startswith(self.committee_prefix)


@dataclass(frozen=True, slots=True)
class Found:
    entry: CatalogEntry
    score: float


class CatalogStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_root()

    @property
    def stubs(self) -> Path:
        return self.root / "catalog"

    @property
    def index_path(self) -> Path:
        return self.root / "catalog.sqlite"

    # --- stubs ---

    def write(self, entry: CatalogEntry) -> Path:
        """Write (or replace) the stub of `entry`. Refuses a location inside a git work tree."""
        ensure_outside_repo(self.stubs / "x", "a catalog stub")
        path = self.stubs / f"{entry.key}.json"
        atomic_write(path, (json.dumps(entry.to_json(), indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        return path

    def write_all(self, entries: Iterable[CatalogEntry]) -> int:
        count = 0
        for entry in entries:
            self.write(entry)
            count += 1
        return count

    def entries(self) -> Iterator[CatalogEntry]:
        if not self.stubs.is_dir():
            return
        for path in sorted(self.stubs.glob("*.json")):
            try:
                yield CatalogEntry.from_json(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise LibError(
                    f"the stub {path} is unreadable ({type(exc).__name__})", "delete it and sync again"
                ) from exc

    # --- the index ---

    def build_index(self) -> int:
        """Rebuild `catalog.sqlite` from the stubs. Returns the number of records indexed."""
        entries = list(self.entries())
        index.rebuild(self.index_path, (as_document(e) for e in entries), rebuild_command=REBUILD)
        conn = index.open_write(self.index_path, rebuild_command=REBUILD)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_META)
            conn.executemany(
                "INSERT OR REPLACE INTO catalog_meta(doc_id, kind, status, free, amount, currency, committee, ics) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        e.key,
                        e.kind,
                        e.status,
                        None if e.price is None else int(e.price.is_free),
                        None if e.price is None else str(e.price.amount),
                        "" if e.price is None else e.price.currency,
                        e.committee,
                        " ".join(e.ics),
                    )
                    for e in entries
                ],
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        return len(entries)

    def search(
        self,
        query: str,
        *,
        category: str | None = None,
        status: str | None = None,
        free: bool | None = None,
        limit: int = 10,
    ) -> list[Found]:
        """Keyword search over the stubs, best first, filtered by category, status and free/priced."""
        by_key = {entry.key: entry for entry in self.entries()}
        conn = index.open_read(self.index_path, rebuild_command=REBUILD)
        try:
            result = index.search(conn, query, limit=max(limit * 20, 100))
            meta = {row[0]: row for row in conn.execute("SELECT doc_id, kind, status, free FROM catalog_meta")}
        except sqlite3.DatabaseError as exc:
            raise LibError(f"the catalog index is unreadable ({exc})", f"run: {REBUILD}") from exc
        finally:
            conn.close()
        found: list[Found] = []
        for hit in result.hits:
            row = meta.get(hit.doc_id)
            entry = by_key.get(hit.doc_id)
            if row is None or entry is None:
                continue
            if category is not None and row[1] != category:
                continue
            if status is not None and row[2] != status:
                continue
            if free is not None and row[3] != int(free):
                continue
            found.append(Found(entry, hit.score))
            if len(found) == limit:
                break
        return found

    def select(
        self, where: CatalogFilter, query: str | None = None, *, limit: int | None = None
    ) -> list[CatalogEntry]:
        """Records passing `where`: ranked by `query` when given, else by designation. Reads the stubs, so it needs
        no index unless a query is given."""
        if query:
            ranked = [f.entry for f in self.search(query, limit=10_000)]
        else:
            ranked = sorted(self.entries(), key=lambda e: (e.designation, e.title))
        chosen = [entry for entry in ranked if where.matches(entry)]
        return chosen if limit is None else chosen[:limit]

    def browse(self, category: str) -> list[CatalogEntry]:
        """Every stored record of one category (`ics`, `committee`, `standard`), by designation. No keywords."""
        return sorted((e for e in self.entries() if e.kind == category), key=lambda e: (e.designation, e.title))
