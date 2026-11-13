"""Parser for data/sources.toml, the list of publications ``usblib-fetch`` may download."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED = ("doc_id", "url", "number", "title", "date", "status")
_KNOWN = (*_REQUIRED, "sha256")


class SourcesError(ValueError):
    """Raised when sources.toml is missing, malformed, or inconsistent."""


@dataclass(frozen=True, slots=True)
class Source:
    """One entry of sources.toml. ``sha256`` is empty until recorded."""

    doc_id: str
    url: str
    number: str
    title: str
    date: str
    status: str
    sha256: str = ""


def parse_sources(text: str) -> tuple[Source, ...]:
    """Parse the text of sources.toml: an array of ``[[source]]`` tables."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SourcesError(f"sources.toml is not valid TOML: {error}") from error
    entries = data.get("source")
    if not isinstance(entries, list) or not entries:
        raise SourcesError("sources.toml has no [[source]] entries")
    sources: list[Source] = []
    seen: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        label = f"source #{position}"
        if not isinstance(entry, dict):
            raise SourcesError(f"{label}: not a table")
        missing = [
            key
            for key in _REQUIRED
            if not isinstance(entry.get(key), str) or not entry[key].strip()
        ]
        if missing:
            raise SourcesError(
                f"{label}: missing or empty field(s): {', '.join(missing)}"
            )
        unknown = sorted(set(entry) - set(_KNOWN))
        if unknown:
            raise SourcesError(f"{label}: unknown field(s): {', '.join(unknown)}")
        doc_id = entry["doc_id"]
        label = f"source {doc_id!r}"
        if not _DOC_ID.match(doc_id):
            raise SourcesError(f"{label}: doc_id must be a lowercase file-safe slug")
        if doc_id in seen:
            raise SourcesError(f"{label}: duplicate doc_id")
        seen.add(doc_id)
        if not entry["url"].startswith("https://"):
            raise SourcesError(f"{label}: url must be https")
        if not _DATE.match(entry["date"]):
            raise SourcesError(f"{label}: date must be YYYY-MM, got {entry['date']!r}")
        digest = entry.get("sha256", "")
        if digest and not _SHA256.match(digest):
            raise SourcesError(f"{label}: sha256 must be 64 lowercase hex digits")
        sources.append(Source(**{key: entry[key] for key in _KNOWN if key in entry}))
    return tuple(sources)


def load_sources(path: Path) -> tuple[Source, ...]:
    """Read and parse ``path``."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourcesError(f"cannot read {path}: {error}") from error
    return parse_sources(text)
