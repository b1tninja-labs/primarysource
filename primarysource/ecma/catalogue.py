"""The Ecma catalogue: which standards and editions, where to fetch them, and the sha256 of each. Metadata only.

`catalogue.json` is package data. Starting with ECMA-427 (Package-URL, 1st edition, December 2025). An edition is
identified by the standard's number and its edition number; a ref names the number (`ecma:427`) and optionally the
edition (`ecma:427@1`); with no edition the highest imported one is read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.errors import LibError

NUMBER = re.compile(r"[0-9]{1,4}")
SHA256 = re.compile(r"[0-9a-f]{64}")
HOSTS = ("ecma-international.org", "www.ecma-international.org")


@dataclass(frozen=True, slots=True)
class Terms:
    licence: str
    placement: str
    terms_url: str
    terms_read: str
    summary: str


@dataclass(frozen=True, slots=True)
class Edition:
    """One edition of one Ecma standard, with its pinned PDF."""

    number: str
    edition: int
    designation: str
    title: str
    edition_name: str
    page_url: str
    source_url: str
    size: int
    sha256: str

    @property
    def key(self) -> str:
        """The file stem under the install directory: `427-1`."""
        return f"{self.number}-{self.edition}"


@dataclass(frozen=True, slots=True)
class Catalogue:
    terms: Terms
    editions: tuple[Edition, ...]

    def edition(self, number: str, edition: int | None = None) -> Edition:
        """The catalogued edition of `number` (the highest if `edition` is None)."""
        have = [e for e in self.editions if e.number == number and (edition is None or e.edition == edition)]
        if not have:
            known = ", ".join(f"{e.number}@{e.edition}" for e in self.editions)
            raise LibError(
                f"no Ecma standard {number}{'@' + str(edition) if edition else ''} in the catalogue",
                f"known: {known}",
            )
        return max(have, key=lambda e: e.edition)


def parse_catalogue(raw: dict[str, Any]) -> Catalogue:
    """Validate a catalogue document. Raises `ValueError`: a malformed catalogue is a packaging bug."""
    terms = raw["terms"]
    if terms["placement"] not in ("layer", "volume"):
        raise ValueError("terms.placement must be 'layer' or 'volume'")
    editions: list[Edition] = []
    for entry in raw["editions"]:
        found = Edition(
            str(entry["number"]),
            int(entry["edition"]),
            entry["designation"],
            entry["title"],
            entry["edition_name"],
            entry["page_url"],
            entry["source_url"],
            int(entry["size"]),
            entry["sha256"],
        )
        if not NUMBER.fullmatch(found.number) or not SHA256.fullmatch(found.sha256) or found.edition < 1:
            raise ValueError(f"catalogue entry {found.designation!r} is malformed")
        editions.append(found)
    if len({e.key for e in editions}) != len(editions):
        raise ValueError("duplicate editions in the catalogue")
    return Catalogue(
        Terms(terms["licence"], terms["placement"], terms["terms_url"], terms["terms_read"], terms["summary"]),
        tuple(editions),
    )


def catalogue() -> Catalogue:
    text = resources.files("primarysource.ecma").joinpath("catalogue.json").read_text(encoding="utf-8")
    return parse_catalogue(json.loads(text))
