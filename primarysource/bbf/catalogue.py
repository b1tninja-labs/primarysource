"""The Broadband Forum catalogue: data-model XML pinned to a commit, and Technical Reports pinned by sha256.

Two kinds of source, two licences, two placements (`terms`):
- `models`: XML files of https://github.com/BroadbandForum/cwmp-data-models at one pinned commit. Each file
  carries a BSD-3-Clause-style notice (redistribution with notice permitted), so placement may be an image layer.
- `reports`: Technical Report PDFs (TR-069 Amendment 6 Corrigendum 1 so far). The Forum's terms of use allow
  use for implementing and distribution only as a whole copy with the notice, and forbid modification or
  derivative works, so they are fetched by the user into a volume.

Metadata only, never text. `catalogue.json` is package data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from primarysource.errors import LibError

DOC_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
HOSTS = ("raw.githubusercontent.com", "www.broadband-forum.org")


@dataclass(frozen=True, slots=True)
class Terms:
    licence: str
    placement: str
    terms_url: str
    terms_read: str
    summary: str


@dataclass(frozen=True, slots=True)
class Model:
    """One data-model XML file at the pinned commit."""

    id: str
    path: str
    title: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Report:
    """One Technical Report PDF."""

    id: str
    designation: str
    title: str
    issue: str
    page_url: str
    source_url: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Catalogue:
    repo: str
    commit: str
    raw_base: str
    model_terms: Terms
    report_terms: Terms
    models: tuple[Model, ...]
    reports: tuple[Report, ...]

    def model(self, doc_id: str) -> Model:
        for found in self.models:
            if found.id == doc_id:
                return found
        raise LibError(f"no BBF data model {doc_id!r} in the catalogue", "bbf_docs lists what is catalogued")

    def report(self, doc_id: str) -> Report:
        for found in self.reports:
            if found.id == doc_id:
                return found
        raise LibError(f"no BBF report {doc_id!r} in the catalogue", "bbf_docs lists what is catalogued")

    def model_url(self, model: Model) -> str:
        return f"{self.raw_base}{self.commit}/{model.path}"


def _terms(raw: dict[str, Any]) -> Terms:
    terms = Terms(raw["licence"], raw["placement"], raw["terms_url"], raw["terms_read"], raw["summary"])
    if terms.placement not in ("layer", "volume"):
        raise ValueError("terms.placement must be 'layer' or 'volume'")
    return terms


def parse_catalogue(raw: dict[str, Any]) -> Catalogue:
    """Validate a catalogue document. Raises `ValueError`: a malformed catalogue is a packaging bug."""
    if not COMMIT.fullmatch(raw["commit"]):
        raise ValueError("catalogue commit must be 40 lowercase hex digits")
    models = tuple(Model(m["id"], m["path"], m["title"], int(m["size"]), m["sha256"]) for m in raw["models"])
    reports = tuple(
        Report(
            r["id"],
            r["designation"],
            r["title"],
            r["issue"],
            r["page_url"],
            r["source_url"],
            int(r["size"]),
            r["sha256"],
        )
        for r in raw["reports"]
    )
    entries: list[Model | Report] = [*models, *reports]
    for entry in entries:
        if not DOC_ID.fullmatch(entry.id) or not SHA256.fullmatch(entry.sha256):
            raise ValueError(f"catalogue entry {entry.id!r} is malformed")
    for model in models:
        if model.path != f"{model.id}.xml":
            raise ValueError(f"catalogue entry {model.id!r}: path must be <id>.xml")
    ids = [e.id for e in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate ids in the catalogue")
    return Catalogue(
        raw["repo"],
        raw["commit"],
        raw["raw_base"],
        _terms(raw["terms"]["models"]),
        _terms(raw["terms"]["reports"]),
        models,
        reports,
    )


def catalogue() -> Catalogue:
    text = resources.files("primarysource.bbf").joinpath("catalogue.json").read_text(encoding="utf-8")
    return parse_catalogue(json.loads(text))
