"""The drafts the portfolio tracks: why each is tracked, the revision last read, and the pins. Metadata only.

`tracked.json` is package data. For each draft it holds what the importer was last run against: the latest
revision read, the datatracker state then, what replaced it, and the sha256 of the files fetched for each
revision read. Those digests are the pins: an import of a revision that has one refuses a different file. A
revision with no pin is trusted on first use and its digest recorded in the library's `meta.json`; add it here
after checking it (`primarysource draft import --print-pin`).

The snapshot says "as of `checked`". It is the catalogue's memory, not the datatracker's current word: `info`
prefers the library's own `status.json` and falls back to this when the draft was never fetched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.draft import names
from primarysource.errors import LibError

PLACEMENTS = ("layer", "volume", "none")


@dataclass(frozen=True, slots=True)
class Terms:
    """What the IETF Trust's terms allow, and so where drafts may be placed (docs/draft.md)."""

    licence: str
    placement: str
    terms_url: str
    terms_read: str
    summary: str


@dataclass(frozen=True, slots=True)
class Pin:
    """sha256 of the files fetched for one revision; None for a file that was not fetched (no XML)."""

    txt: str | None
    xml: str | None


@dataclass(frozen=True, slots=True)
class Tracked:
    name: str
    why: str
    consumers: tuple[str, ...]
    rev_read: str
    state: str
    replaced_by: tuple[str, ...]
    became_rfc: str | None
    expires: str
    checked: str
    pins: dict[str, Pin]


def _digest(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64 or value.strip("0123456789abcdef"):
        raise ValueError(f"{where}: a sha256 must be 64 lowercase hex digits or null")
    return value


def parse(raw: str) -> tuple[Terms, dict[str, Tracked]]:
    """Validate the catalogue text. A malformed catalogue is a packaging bug, so it raises ValueError."""
    data = json.loads(raw)
    if data.get("schema") != 1:
        raise ValueError("catalogue schema must be 1")
    t = data["terms"]
    if t["placement"] not in PLACEMENTS:
        raise ValueError(f"placement {t['placement']!r} is not one of {PLACEMENTS}")
    terms = Terms(t["licence"], t["placement"], t["terms_url"], t["terms_read"], t["summary"])
    drafts: dict[str, Tracked] = {}
    for entry in data["drafts"]:
        name = names.parse_name(entry["name"])
        if name in drafts:
            raise ValueError(f"duplicate draft {name}")
        pins: dict[str, Pin] = {}
        for rev, files in entry["pins"].items():
            names.valid_revision(rev)
            pins[rev] = Pin(_digest(files.get("txt"), f"{name}-{rev}"), _digest(files.get("xml"), f"{name}-{rev}"))
        if entry["rev_read"]:
            names.valid_revision(entry["rev_read"])
        drafts[name] = Tracked(
            name,
            entry["why"],
            tuple(entry["consumers"]),
            entry["rev_read"],
            entry["state"],
            tuple(entry["replaced_by"]),
            entry["became_rfc"],
            entry["expires"],
            entry["checked"],
            pins,
        )
    return terms, drafts


TERMS, TRACKED = parse(resources.files("primarysource.draft").joinpath("tracked.json").read_text(encoding="utf-8"))


def pin_for(name: str, rev: str) -> Pin | None:
    """The pinned digests for one revision of a tracked draft, or None."""
    tracked = TRACKED.get(name)
    return tracked.pins.get(rev) if tracked else None


def tracked(name: str) -> Tracked:
    """The catalogue entry, or a LibError that lists what is tracked."""
    found = TRACKED.get(names.parse_name(name))
    if found is None:
        known = ", ".join(sorted(TRACKED)) or "none"
        raise LibError(f"{name} is not in the tracked catalogue (tracked: {known})", "")
    return found
