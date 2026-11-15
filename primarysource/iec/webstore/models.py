"""Catalogue models, parsed from the search API's `_source` objects (docs/iec-webstore.md, "Search").

Everything here is metadata: designation, title, edition, status, price, committee, ICS, formats, lifecycle. The
`abstract` is the store's own
catalogue blurb, not a standard's text; the owner decided on 2026-11-14 that it is collected (stub writer and
index keep it unless told not to).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from primarysource.errors import LibError

__all__ = [
    "Committee",
    "FileFormat",
    "Ics",
    "Lifecycle",
    "Price",
    "Publication",
    "SearchPage",
    "parse_publication",
    "parse_search",
]

CHANGED = "the search API may have changed; see docs/iec-webstore.md"


@dataclass(frozen=True, slots=True)
class Price:
    amount: float
    currency: str

    @property
    def is_free(self) -> bool:
        return self.amount == 0

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:g}"


@dataclass(frozen=True, slots=True)
class Committee:
    level_1: str
    level_1_name: str = ""
    level_2: str = ""
    level_2_name: str = ""


@dataclass(frozen=True, slots=True)
class Ics:
    code: str
    title: str = ""
    level_1_title: str = ""


@dataclass(frozen=True, slots=True)
class FileFormat:
    """One downloadable form of a publication: PDF/XML/DOC/TRF, a language (`en`, `fr`, `en/fr`), a kind."""

    format: str
    language: str
    kind: str = ""
    has_full_pdf: bool = False


@dataclass(frozen=True, slots=True)
class Lifecycle:
    reference: str
    id: int | None
    edition: str = ""
    status: str = ""
    publication_date: str = ""


@dataclass(frozen=True, slots=True)
class Publication:
    id: int
    reference: str
    title: str
    edition: str = ""
    status: str = ""
    publication_type: str = ""
    publication_date: str = ""
    head: str = ""
    price: Price | None = None
    committee: Committee | None = None
    ics: tuple[Ics, ...] = ()
    formats: tuple[str, ...] = ()
    files: tuple[FileFormat, ...] = ()
    pages: int | None = None
    isbn: str = ""
    urn: str = ""
    lifecycle: tuple[Lifecycle, ...] = ()
    abstract: str | None = field(default=None, repr=False)

    @property
    def is_free(self) -> bool:
        return self.price is not None and self.price.is_free

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.language for f in self.files if f.language))

    @property
    def page_url(self) -> str:
        return f"https://webstore.iec.ch/en/publication/{self.id}"


def _text(value: Any) -> str:
    return "" if value is None else str(value).replace("\r", "").strip()


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _committee(value: Mapping[str, Any] | None) -> Committee | None:
    if not value:
        return None
    return Committee(
        _text(value.get("level_1")),
        _text(value.get("level_1_details")),
        _text(value.get("level_2")),
        _text(value.get("level_2_details")),
    )


def _ics(item: Mapping[str, Any]) -> Ics:
    return Ics(
        _text(item.get("level_3") or item.get("level_2") or item.get("level_1")),
        _text(item.get("level_3_details") or item.get("level_2_details") or item.get("level_1_details")),
        _text(item.get("level_1_details")),
    )


def parse_publication(source: Mapping[str, Any]) -> Publication:
    """One search hit's `_source`. A hit without an id or a reference is an error: the site changed."""
    identifier = _int(source.get("id"))
    reference = _text(source.get("reference"))
    if identifier is None or not reference:
        raise LibError("a search hit has no id or reference", CHANGED)
    price = source.get("price")
    ref_object = source.get("reference_object") or {}
    return Publication(
        id=identifier,
        reference=reference,
        title=_text(source.get("title")),
        edition=_text(source.get("edition")),
        status=_text(source.get("status")),
        publication_type=_text(source.get("publication_type")),
        publication_date=_text(source.get("publication_date")),
        head=_text(ref_object.get("head")),
        price=Price(float(price["amount"]), _text(price.get("currency"))) if price and "amount" in price else None,
        committee=_committee(source.get("committee")),
        ics=tuple(_ics(item) for item in source.get("ics") or ()),
        formats=tuple(_text(f) for f in source.get("available_formats") or ()),
        files=tuple(
            FileFormat(
                _text(f.get("format")), _text(f.get("language")), _text(f.get("type")), bool(f.get("hasFullPdf"))
            )
            for f in source.get("available_files") or ()
        ),
        pages=_int(source.get("pdf_pages")),
        isbn=_text(source.get("isbn")),
        urn=_text(source.get("urn")),
        lifecycle=tuple(
            Lifecycle(
                _text(item.get("reference")),
                _int(item.get("id")),
                _text(item.get("edition")),
                _text(item.get("status")),
                _text(item.get("publication_date")),
            )
            for item in source.get("lifecycle") or ()
        ),
        abstract=_text(source.get("abstract")) or None,
    )


@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page of results. `total` counts the filtered result set (`secondary` in the response); `unfiltered_total`
    counts the whole catalogue slice (`primary`). `facets` maps a facet name (`committee`, `ics`, `type`, ...) to
    `(key, count)` pairs for the filtered set, flattened over the levels of its tree."""

    hits: tuple[Publication, ...]
    total: int
    unfiltered_total: int
    start: int
    facets: Mapping[str, tuple[tuple[str, int], ...]]

    @property
    def next_start(self) -> int | None:
        end = self.start + len(self.hits)
        return end if self.hits and end < self.total else None


_BUCKETS = re.compile(r"^buckets#(.+)$")


def _flatten(node: Any) -> list[tuple[str, int]]:
    """Every `key`/`doc_count` of the first `buckets` list under `node`, each bucket's `nested` tree after it."""
    found: list[tuple[str, int]] = []

    def walk(value: Any) -> None:
        if not isinstance(value, Mapping):
            return
        buckets = value.get("buckets")
        if isinstance(buckets, Sequence) and not isinstance(buckets, str):
            for bucket in buckets:
                if isinstance(bucket, Mapping) and "key" in bucket:
                    found.append((str(bucket["key"]), int(bucket.get("doc_count") or 0)))
                    walk(bucket.get("nested"))
            return
        for child in value.values():
            walk(child)

    walk(node)
    return found


def parse_search(payload: Any, start: int = 0) -> SearchPage:
    """The search API's answer: `{primary, secondary}`, each `{hits: {total, hits}, aggregations}`.

    The result list is `secondary` (what the filters select), as the storefront's own list shows it; if a response
    has no `secondary` the `primary` hits are used.
    """
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("secondary") or payload.get("primary"), Mapping
    ):
        raise LibError("the search API answered an unexpected shape", CHANGED)
    primary: Mapping[str, Any] = payload.get("primary") or {}
    chosen: Mapping[str, Any] = payload.get("secondary") or primary
    hits_block = chosen.get("hits") or {}
    total = _int((hits_block.get("total") or {}).get("value")) or 0
    unfiltered = _int(((primary.get("hits") or {}).get("total") or {}).get("value")) or total
    hits = tuple(parse_publication(h.get("_source") or {}) for h in hits_block.get("hits") or ())
    facets: dict[str, tuple[tuple[str, int], ...]] = {}
    for name, node in (chosen.get("aggregations") or {}).items():
        match = _BUCKETS.match(name)
        if match:
            facets[match.group(1)] = tuple(_flatten(node))
    return SearchPage(hits, total, unfiltered, start, facets)
