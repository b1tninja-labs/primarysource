"""The C2SP catalogue: which specifications, at which commit, with which sha256. Metadata only, never text.

`catalogue.json` is package data. It pins one commit of https://github.com/C2SP/C2SP and, for each top-level
specification file at that commit, its size and sha256. The importer refuses any file whose digest differs, so a
rewritten history or a tampered mirror cannot change what a ref reads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.errors import LibError

DOC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}")
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
HOSTS = ("raw.githubusercontent.com",)


@dataclass(frozen=True, slots=True)
class Terms:
    """What the publisher allows, and therefore where the text may be placed."""

    licence: str
    placement: str
    terms_url: str
    terms_read: str
    summary: str


@dataclass(frozen=True, slots=True)
class Spec:
    """One specification file at the pinned commit."""

    id: str
    path: str
    title: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Catalogue:
    repo: str
    commit: str
    raw_base: str
    terms: Terms
    specs: tuple[Spec, ...]

    def spec(self, doc_id: str) -> Spec:
        for candidate in self.specs:
            if candidate.id == doc_id:
                return candidate
        known = ", ".join(s.id for s in self.specs)
        raise LibError(f"no C2SP specification {doc_id!r} in the catalogue", f"known: {known}")

    def url(self, spec: Spec) -> str:
        return f"{self.raw_base}{self.commit}/{spec.path}"


def parse_catalogue(raw: dict[str, Any]) -> Catalogue:
    """Validate a catalogue document. Raises `ValueError`: a malformed catalogue is a packaging bug."""
    commit = raw["commit"]
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise ValueError("catalogue commit must be 40 lowercase hex digits")
    terms = raw["terms"]
    specs: list[Spec] = []
    for entry in raw["specs"]:
        spec = Spec(entry["id"], entry["path"], entry["title"], int(entry["size"]), entry["sha256"])
        if not DOC_ID.fullmatch(spec.id) or spec.path != f"{spec.id}.md":
            raise ValueError(f"catalogue entry {spec.id!r}: id must be a slug and path <id>.md")
        if not SHA256.fullmatch(spec.sha256):
            raise ValueError(f"catalogue entry {spec.id!r}: sha256 must be 64 hex digits")
        specs.append(spec)
    if len({s.id for s in specs}) != len(specs):
        raise ValueError("duplicate specification ids in the catalogue")
    if terms["placement"] not in ("layer", "volume"):
        raise ValueError("terms.placement must be 'layer' or 'volume'")
    return Catalogue(
        raw["repo"],
        commit,
        raw["raw_base"],
        Terms(terms["licence"], terms["placement"], terms["terms_url"], terms["terms_read"], terms["summary"]),
        tuple(specs),
    )


def catalogue() -> Catalogue:
    """The packaged catalogue."""
    text = resources.files("primarysource.c2sp").joinpath("catalogue.json").read_text(encoding="utf-8")
    return parse_catalogue(json.loads(text))
