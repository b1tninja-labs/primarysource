"""The on-disk library: `$PRIMARYSOURCE_HOME/draft/<name>/<rev>/` per revision, `<name>/status.json` per draft.

    draft-x-y/status.json        the datatracker's last word (status.py), replaced on every refresh
    draft-x-y/03/draft.txt       the archive's text, byte for byte as fetched
    draft-x-y/03/draft.xml       the author's source, when the archive has one
    draft-x-y/03/meta.json       what was fetched, from where, its sha256, and its licence legend
    draft-x-y/03/sections.json   a cache of the segmentation; rebuilt from draft.txt when missing or stale

A revision directory appears whole or not at all (it is built beside the others and renamed into place), and
`meta.json` is what a reader trusts. A stored revision is never overwritten: the archive's revisions do not
change, so a different digest for one is an error to report, not an update to apply.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from primarysource.draft import names, segment
from primarysource.draft.status import Status
from primarysource.errors import LibError
from primarysource.home import atomic_write
from primarysource.home import collection_home as core_collection_home

COLLECTION = "draft"
READONLY_VARIABLE = "PRIMARYSOURCE_READONLY"
_REV_DIR = re.compile(r"[0-9]{2}")


def readonly() -> bool:
    """True when `primarysource mcp --read-only` (or the variable) asked for no writes and no fetching."""
    return os.environ.get(READONLY_VARIABLE, "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class RevMeta:
    """What one stored revision is. `xml_state` is `v2`, `v3`, `absent`, `refused`, `unparseable` or `skipped`."""

    name: str
    rev: str
    title: str
    published: str
    authors: tuple[str, ...]
    txt_sha256: str
    txt_bytes: int
    encoding: str
    xml_state: str
    xml_sha256: str
    xml_bytes: int
    restriction: str
    copyright_year: int
    ipr: str
    imported: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1, ensure_ascii=False) + "\n"

    @staticmethod
    def from_json(text: str) -> RevMeta:
        try:
            raw: dict[str, Any] = json.loads(text)
            values = {f.name: raw[f.name] for f in fields(RevMeta)}
            values["authors"] = tuple(str(a) for a in values["authors"])
            for key in ("txt_bytes", "xml_bytes", "copyright_year"):
                values[key] = int(values[key])
            for key in set(values) - {"authors", "txt_bytes", "xml_bytes", "copyright_year"}:
                values[key] = str(values[key])
            return RevMeta(**values)
        except (ValueError, KeyError, TypeError) as exc:
            raise LibError("a stored revision's meta.json is damaged", "import that revision again") from exc


class Store:
    """One draft library. `root` is the collection's directory; by default `$PRIMARYSOURCE_HOME/draft`."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else core_collection_home(COLLECTION)

    def _dir(self, name: str, rev: str | None = None) -> Path:
        base = self.root / names.parse_name(name)
        return base if rev is None else base / names.valid_revision(rev)

    def path(self, name: str, rev: str) -> Path:
        """Where one revision lives (it may not exist)."""
        return self._dir(name, rev)

    def names(self) -> list[str]:
        """Drafts with at least one stored revision, sorted."""
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.revisions(p.name))

    def revisions(self, name: str) -> list[str]:
        """Stored revisions of `name`, oldest first. A directory without `meta.json` is a failed import: ignored."""
        base = self._dir(name)
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if _REV_DIR.fullmatch(p.name) and (p / "meta.json").is_file())

    def has(self, name: str, rev: str) -> bool:
        return (self._dir(name, rev) / "meta.json").is_file()

    def resolve(self, name: str, rev: str | None) -> tuple[str, bool]:
        """The revision to read and whether it was chosen (True) because none was named: the latest stored."""
        stored = self.revisions(name)
        if rev is not None:
            if rev not in stored:
                have = ", ".join(stored) or "none"
                raise LibError(
                    f"revision {rev} of {name} is not stored (stored: {have})",
                    f"primarysource draft import {name}-{rev}",
                )
            return rev, False
        if not stored:
            raise LibError(f"{name} is not stored", f"primarysource draft import {name}")
        return stored[-1], True

    def meta(self, name: str, rev: str) -> RevMeta:
        path = self._dir(name, rev) / "meta.json"
        try:
            return RevMeta.from_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise LibError(f"{name}-{rev} is not stored", f"primarysource draft import {name}-{rev}") from exc

    def status(self, name: str) -> Status | None:
        """The datatracker snapshot for `name`, or None if it was never fetched."""
        path = self._dir(name) / "status.json"
        try:
            return Status.from_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None

    def write_status(self, status: Status) -> None:
        atomic_write(self._dir(status.name) / "status.json", status.to_json().encode("utf-8"))

    def raw_text(self, name: str, rev: str) -> bytes:
        try:
            return (self._dir(name, rev) / "draft.txt").read_bytes()
        except OSError as exc:
            raise LibError(f"{name}-{rev} has no stored text", f"primarysource draft import {name}-{rev}") from exc

    def segmented(self, name: str, rev: str) -> segment.Segmented:
        """The sections of a stored revision, from the cache when it is current, else from the stored text (and the
        cache is rewritten unless the library is read-only)."""
        folder = self._dir(name, rev)
        try:
            cached = segment.Segmented.from_json((folder / "sections.json").read_text(encoding="utf-8"))
        except OSError:
            cached = None
        if cached is not None:
            return cached
        text, _encoding = segment.decode(self.raw_text(name, rev))
        found = segment.segment(text)
        if not readonly():
            with contextlib.suppress(OSError):  # a read-only volume is a supported place to serve from
                atomic_write(folder / "sections.json", found.to_json().encode("utf-8"))
        return found

    def install(self, meta: RevMeta, txt: bytes, xml: bytes | None, found: segment.Segmented) -> Path:
        """Write one revision whole, or not at all. Refuses to replace a stored revision."""
        target = self._dir(meta.name, meta.rev)
        if (target / "meta.json").is_file():
            raise LibError(f"{meta.name}-{meta.rev} is already stored", "")
        base = target.parent
        base.mkdir(parents=True, exist_ok=True)
        staging = base / f".{meta.rev}.part-{secrets.token_hex(4)}"
        staging.mkdir()
        try:
            atomic_write(staging / "draft.txt", txt)
            if xml is not None:
                atomic_write(staging / "draft.xml", xml)
            atomic_write(staging / "sections.json", found.to_json().encode("utf-8"))
            atomic_write(staging / "meta.json", meta.to_json().encode("utf-8"))
            if target.exists():  # a failed earlier import left a directory without meta.json
                shutil.rmtree(target)
            os.replace(staging, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return target
