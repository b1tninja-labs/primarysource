"""The catalogue of IEEE editions: designations, titles, sources and pins. Metadata only, never text.

`catalogue.json` is package data. The pins it holds are also exposed as module constants (`POSIX_2024`,
`POSIX_TERMS`, `IEEE802_TERMS`) so that the core's collection manifest (`cl.collection_manifest`, owned by the
core) can lift them when it lands. Until then this module is the only reader of the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.errors import LibError

PLACEMENTS = ("layer", "volume", "none")


@dataclass(frozen=True, slots=True)
class Terms:
    """What a collection's publisher allows, and therefore where its text may be placed."""

    collection: str
    licence: str
    placement: str
    terms_url: str
    terms_read: str
    summary: str


@dataclass(frozen=True, slots=True)
class Edition:
    """One edition of one document. `sha256` is None until a pin exists (an 802 PDF the user has not supplied)."""

    collection: str
    id: str
    designations: tuple[str, ...]
    title: str
    publisher: str
    edition_date: str
    page_url: str
    source_url: str | None
    archive: str | None
    sha256: str | None
    size: int | None
    root: str | None = None


def _text(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"catalogue entry {entry.get('id')!r}: {key} must be a non-empty string")
    return value


def _optional(entry: dict[str, Any], key: str) -> str | None:
    value = entry.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"catalogue entry {entry.get('id')!r}: {key} must be a string or null")
    return value


def parse(raw: str) -> tuple[dict[str, Terms], dict[str, Edition]]:
    """Validate the catalogue text. A malformed catalogue is a packaging bug, so it raises ValueError."""
    data = json.loads(raw)
    if data.get("schema") != 1:
        raise ValueError("catalogue schema must be 1")
    terms: dict[str, Terms] = {}
    editions: dict[str, Edition] = {}
    for collection, body in data["collections"].items():
        placement = _text(body, "placement")
        if placement not in PLACEMENTS:
            raise ValueError(f"{collection}: placement {placement!r} is not one of {PLACEMENTS}")
        terms[collection] = Terms(
            collection,
            _text(body, "licence"),
            placement,
            _text(body, "terms_url"),
            _text(body, "terms_read"),
            _text(body, "terms_summary"),
        )
        for entry in body["editions"]:
            digest = _optional(entry, "sha256")
            if digest is not None and (len(digest) != 64 or digest.strip("0123456789abcdef")):
                raise ValueError(f"{entry.get('id')!r}: sha256 must be 64 lowercase hex digits")
            size = entry.get("size")
            if size is not None and (not isinstance(size, int) or size <= 0):
                raise ValueError(f"{entry.get('id')!r}: size must be a positive integer or null")
            edition = Edition(
                collection,
                _text(entry, "id"),
                tuple(entry["designations"]),
                _text(entry, "title"),
                _text(entry, "publisher"),
                _text(entry, "edition_date"),
                _text(entry, "page_url"),
                _optional(entry, "source_url"),
                _optional(entry, "archive"),
                digest,
                size,
                _optional(entry, "root"),
            )
            if edition.id in editions:
                raise ValueError(f"duplicate edition id {edition.id!r}")
            editions[edition.id] = edition
    return terms, editions


TERMS, EDITIONS = parse(resources.files("primarysource.ieee").joinpath("catalogue.json").read_text(encoding="utf-8"))

POSIX_TERMS = TERMS["posix"]
IEEE802_TERMS = TERMS["ieee802"]
POSIX_2024 = EDITIONS["posix-2024"]


def edition(collection: str, edition_id: str) -> Edition:
    """The catalogued edition, or a LibError that lists the ones this collection knows."""
    found = EDITIONS.get(edition_id)
    if found is None or found.collection != collection:
        known = ", ".join(sorted(e.id for e in EDITIONS.values() if e.collection == collection)) or "none"
        raise LibError(f"{edition_id!r} is not in the {collection} catalogue (known: {known})", "")
    return found
