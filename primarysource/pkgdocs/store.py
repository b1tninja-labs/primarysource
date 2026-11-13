"""An installed edition: parsed documents and a search index under `$PRIMARYSOURCE_HOME/<collection>/`.

    <collection>/<tree>/<commit>/edition.json    what was imported, from where, under which digest
                                 index.json       the documents (id, title, file, meta) and chapter aliases
                                 docs/<n>.json    one parsed document
                                 index.sqlite     the full-text index

An edition is written into a staging directory beside its destination and renamed into place, so a reader sees
the old edition or the new one. What is stored is the parsed sections, not the archive and not the repository;
nothing in this module or its caller writes under the source tree.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from primarysource.errors import LibError
from primarysource.pkgdocs import index
from primarysource.pkgdocs.model import Doc

RECORD = "edition.json"
CATALOGUE = "index.json"
SEARCH = "index.sqlite"
_COMMIT = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class Entry:
    """A document as listed in the edition's catalogue."""

    id: str
    title: str
    file: str
    sections: int
    meta: Mapping[str, str]


class Edition:
    """One installed edition, opened for reading."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.record: dict[str, Any] = json.loads((path / RECORD).read_text(encoding="utf-8"))
            listing = json.loads((path / CATALOGUE).read_text(encoding="utf-8"))
            self.entries: dict[str, Entry] = {
                str(e["id"]): Entry(
                    str(e["id"]), str(e["title"]), str(e["file"]), int(e["sections"]), dict(e["meta"])
                )
                for e in listing["docs"]
            }
            self.aliases: dict[str, str] = {str(k): str(v) for k, v in listing["aliases"].items()}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibError(f"the edition at {path} is damaged ({exc})", "", "import it again") from exc

    @property
    def commit(self) -> str:
        return str(self.record["commit"])

    @property
    def label(self) -> str:
        return str(self.record.get("label", ""))

    def load(self, doc_id: str) -> Doc:
        entry = self.entries.get(doc_id)
        if entry is None:
            raise LibError(f"no document {doc_id!r} in this edition", "list the documents first")
        try:
            return Doc.from_json(json.loads((self.path / "docs" / entry.file).read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise LibError(f"document {doc_id!r} is unreadable ({exc})", "", "import the edition again") from exc

    @property
    def index_path(self) -> Path:
        return self.path / SEARCH


def write_edition(
    base: Path,
    commit: str,
    record: Mapping[str, Any],
    docs: Sequence[Doc],
    aliases: Mapping[str, str] | None = None,
) -> Path:
    """Install `docs` as `<base>/<commit>`, replacing an earlier install of the same commit. Returns the path."""
    if not commit or not set(commit) <= _COMMIT:
        raise LibError(f"{commit!r} is not a commit id", "a pin names a full lowercase hex commit")
    base.mkdir(parents=True, exist_ok=True)
    staging = base / f".{commit}.part-{secrets.token_hex(4)}"
    staging.mkdir()
    try:
        (staging / "docs").mkdir()
        listing: list[dict[str, Any]] = []
        for number, doc in enumerate(docs, start=1):
            name = f"{number:05d}.json"
            (staging / "docs" / name).write_text(json.dumps(doc.to_json(), ensure_ascii=False), encoding="utf-8")
            listing.append(
                {
                    "id": doc.id,
                    "title": doc.title,
                    "file": name,
                    "sections": len(doc.sections),
                    "meta": dict(doc.meta),
                }
            )
        (staging / CATALOGUE).write_text(
            json.dumps({"docs": listing, "aliases": dict(aliases or {})}, ensure_ascii=False, indent=0),
            encoding="utf-8",
        )
        sections = index.build(staging / SEARCH, docs)
        (staging / RECORD).write_text(
            json.dumps({**record, "commit": commit, "docs": len(docs), "sections": sections}, indent=2) + "\n",
            encoding="utf-8",
        )
        target = base / commit
        old = base / f".{commit}.old-{secrets.token_hex(4)}"
        if target.exists():
            os.replace(target, old)
        try:
            os.replace(staging, target)
        except BaseException:
            if old.exists():
                os.replace(old, target)
            raise
        shutil.rmtree(old, ignore_errors=True)
        return target
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def installed(base: Path) -> list[Edition]:
    """Every readable edition under `base`, newest import first. A damaged one is skipped, not hidden by
    raising: `find` reports the damage when it is the one asked for."""
    found: list[Edition] = []
    if not base.is_dir():
        return found
    for child in sorted(base.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and (child / RECORD).is_file():
            try:
                found.append(Edition(child))
            except LibError:
                continue
    found.sort(key=lambda e: str(e.record.get("imported", "")), reverse=True)
    return found


def find(base: Path, commit: str | None, what: str, hint: str) -> Edition:
    """The edition whose commit starts with `commit`, or the newest import when `commit` is None."""
    editions = installed(base)
    if not editions:
        raise LibError(f"{what} is not imported (nothing under {base})", hint)
    if commit is None:
        return editions[0]
    matches = [e for e in editions if e.commit.startswith(commit.lower())]
    if len(matches) == 1:
        return matches[0]
    have = ", ".join(e.commit[:12] for e in editions)
    if not matches:
        raise LibError(f"no imported edition of {what} has a commit starting {commit!r} (have: {have})", hint)
    raise LibError(f"{commit!r} matches more than one edition of {what} ({have})", "give more of the commit")
