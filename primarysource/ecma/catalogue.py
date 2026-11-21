"""The Ecma catalogue: which standards and editions, where to fetch them, and the sha256 of each. Metadata only.

`catalogue.json` is package data, including ECMA-119 (5th edition, December 2024), ECMA-167 (3rd edition,
June 1997) and ECMA-427 (Package-URL, 1st edition, December 2025). An edition is identified by the standard's
number and its edition number; a ref names the number (`ecma:427`) and optionally the edition (`ecma:427@1`);
with no edition the highest imported one is read.

`identical` is set only when that edition's own page states the edition is fully identical with the named ISO
designation. An ISO number printed in the page's classification is a cross-reference, not that statement, and
stays off this field.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.errors import LibError
from primarysource.iso.designation import parse as parse_designation

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
    identical: tuple[str, ...] = ()
    """ISO designations this edition's page states it is fully identical with. Empty when the page does not."""

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


def same_text(number: str, year: str | None = None, cat: Catalogue | None = None) -> tuple[Edition, ...]:
    """Editions whose page states that they are fully identical with ISO standard `number`.

    `year` is the part of a ref after `@` (`1994`). An amendment token (`1994+amd1-2022`) matches nothing,
    because the statement names one edition. With no year, every such edition of that number is returned.
    """
    if year and "+" in year:
        return ()
    cat = cat or catalogue()
    found: list[Edition] = []
    for edition in cat.editions:
        for label in edition.identical:
            designation = parse_designation(label)
            if designation.number != number:
                continue
            if year is not None and str(designation.year) != year:
                continue
            found.append(edition)
            break
    return tuple(found)


def identical_with(number: str, edition: int, cat: Catalogue | None = None) -> str:
    """The ISO designations `number@edition` is fully identical with, or empty when it is not in the catalogue."""
    cat = cat or catalogue()
    try:
        found = cat.edition(number, edition)
    except LibError:
        return ""
    return ", ".join(found.identical)


def parse_catalogue(raw: dict[str, Any]) -> Catalogue:
    """Validate a catalogue document. Raises `ValueError`: a malformed catalogue is a packaging bug."""
    terms = raw["terms"]
    if terms["placement"] not in ("layer", "volume"):
        raise ValueError("terms.placement must be 'layer' or 'volume'")
    editions: list[Edition] = []
    for entry in raw["editions"]:
        raw_identical = entry.get("identical", [])
        designation = str(entry["designation"])
        if not isinstance(raw_identical, list) or not all(isinstance(item, str) for item in raw_identical):
            raise ValueError(f"catalogue entry {designation!r} identical must be a list of designations")
        for item in raw_identical:
            try:
                parse_designation(item)
            except LibError as exc:
                raise ValueError(f"catalogue entry {designation!r} identical {item!r} is not a designation") from exc
        found = Edition(
            str(entry["number"]),
            int(entry["edition"]),
            designation,
            entry["title"],
            entry["edition_name"],
            entry["page_url"],
            entry["source_url"],
            int(entry["size"]),
            entry["sha256"],
            tuple(raw_identical),
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
