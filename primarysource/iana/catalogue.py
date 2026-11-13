"""The catalogue of registries the portfolio needs, and IANA's terms for them. Metadata only, never content.

`catalogue.json` is package data. Each entry has the registry file's name, its URL and the date the URL was last
confirmed to serve a registry file (`read`). `likely_users` names the portfolio projects that want the data and is
indicative, not a dependency declaration. Any other registry under `https://www.iana.org/assignments/` can be
imported by name too (`primarysource iana import <name>`); the catalogue is the list the portfolio needs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.errors import LibError

BASE = "https://www.iana.org/assignments/"
NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")


@dataclass(frozen=True, slots=True)
class Terms:
    licence: str
    placement: str
    terms_url: str
    terms_read: str
    summary: str


@dataclass(frozen=True, slots=True)
class Entry:
    name: str
    title: str
    url: str
    likely_users: str
    read: str


def url_for(name: str) -> str:
    """`https://www.iana.org/assignments/<name>/<name>.xml`, the layout every registry file follows."""
    if not NAME.fullmatch(name) or ".." in name:
        raise LibError(
            f"{name!r} is not a registry file name", "names are lowercase letters, digits, '-', '_' and '.'"
        )
    return f"{BASE}{name}/{name}.xml"


def _load() -> tuple[Terms, tuple[Entry, ...]]:
    raw: dict[str, Any] = json.loads(
        resources.files("primarysource.iana").joinpath("catalogue.json").read_text("utf-8")
    )
    t = raw["terms"]
    terms = Terms(t["licence"], t["placement"], t["terms_url"], t["terms_read"], t["summary"])
    entries = tuple(
        Entry(e["name"], e["title"], e["url"], e.get("likely_users", ""), e["read"]) for e in raw["registries"]
    )
    for entry in entries:
        if entry.url != url_for(entry.name):
            raise ValueError(f"catalogue entry {entry.name!r} has an unexpected URL {entry.url!r}")
    return terms, entries


TERMS, ENTRIES = _load()


def entry(name: str) -> Entry | None:
    return next((e for e in ENTRIES if e.name == name), None)
