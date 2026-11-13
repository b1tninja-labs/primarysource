"""Make the installed library match a manifest: plan first, then (unless a dry run) download what is missing.

A manifest is TOML and names catalogue entries only:

    libraries = ["devdocs_en_python", "devdocs_en_rust"]
    groups = ["web-testing"]          # named sets from zimlore.groups
    max_age_days = 365                # flag installed editions older than this
    budget = "2GB"                    # the library may not grow past this on disk

It may be committed to a project: it can name nothing that executes, because every entry is validated as a bare
catalogue name (no scheme, no slash, no colon) and unknown keys are errors. All network goes through `catalog.py`.
Nothing here deletes: an installed library the manifest does not name is reported as an extra and left alone, and
an update is a new dated file beside the old edition, exactly as `zimlore get` stages it.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from . import catalog, groups, library
from .errors import ZimloreError

MANIFEST_NAME = ".zimlore.toml"
HOME_MANIFEST = "libraries.toml"
KEYS = {"libraries", "groups", "max_age_days", "budget"}
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}


@dataclass(frozen=True)
class Manifest:
    path: Path | None = None
    libraries: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    max_age_days: int | None = None
    budget: int | None = None


def check_name(name: object, where: str) -> str:
    """A catalogue name and nothing else. `https://x/y.zim`, `../a`, `C:\\a` and `a.zim` are all refused."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name.endswith(".zim"):
        raise ZimloreError(
            f"{where}: {name!r} is not a catalogue name",
            "a manifest names catalogue entries (zimlore catalog <words> finds them), never URLs or paths",
        )
    return name


def parse_budget(value: object) -> int:
    """`"2GB"`, `"500 MB"`, `"1.5GB"` (decimal units, as the CLI prints sizes) or an integer number of bytes."""
    if isinstance(value, bool):
        raise ZimloreError(f"budget {value!r} is not a size", 'write it as "2GB" or a number of bytes')
    if isinstance(value, int) and value > 0:
        return value
    match = (
        re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?B)?\s*", value, re.IGNORECASE) if isinstance(value, str) else None
    )
    if not match or float(match.group(1)) <= 0:
        raise ZimloreError(f"budget {value!r} is not a size", 'write it as "2GB", "500MB" or a number of bytes')
    return int(float(match.group(1)) * UNITS[(match.group(2) or "B").upper()])


def find_manifest(explicit: str = "", cwd: Path | None = None) -> Path | None:
    """--manifest, else `./.zimlore.toml`, else `$ZIMLORE_HOME/libraries.toml`; None when there is none. An
    explicit path that does not exist is an error rather than a silent fall-through to another manifest."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ZimloreError(f"manifest {path} does not exist", "check the --manifest path")
        return path
    for candidate in ((cwd or Path.cwd()) / MANIFEST_NAME, library.home() / HOME_MANIFEST):
        if candidate.is_file():
            return candidate
    return None


def load_manifest(path: Path) -> Manifest:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ZimloreError(f"{path} is not a readable TOML manifest ({error})", f"fix or delete {path}") from error
    unknown = sorted(set(raw) - KEYS)
    if unknown:
        raise ZimloreError(f"{path}: unknown key(s) {unknown}", f"a manifest has only {sorted(KEYS)}")
    libs, named = raw.get("libraries", []), raw.get("groups", [])
    if not isinstance(libs, list) or not isinstance(named, list):
        raise ZimloreError(f"{path}: libraries and groups must be lists of names")
    known = sorted(groups.GROUPS)
    for group in named:
        if group not in groups.GROUPS:
            raise ZimloreError(f"{path}: unknown group {group!r}", f"the groups are {known}")
    age = raw.get("max_age_days")
    if age is not None and (isinstance(age, bool) or not isinstance(age, int) or age < 1):
        raise ZimloreError(f"{path}: max_age_days must be a positive whole number")
    budget = parse_budget(raw["budget"]) if "budget" in raw else None
    return Manifest(
        path,
        tuple(check_name(name, f"{path} libraries") for name in libs),
        tuple(named),
        age,
        budget,
    )


@dataclass
class Item:
    name: str
    action: str  # install | update | current | outdated | unlisted | blocked | unavailable
    installed: str | None = None
    available: str | None = None
    approx_bytes: int = 0
    over_max_age: bool = False
    note: str = ""
    file: str = ""
    entry: catalog.CatalogEntry | None = field(default=None, repr=False)


@dataclass
class Plan:
    manifest: Path | None
    items: list[Item]
    extras: list[dict[str, Any]]
    download_bytes: int
    installed_bytes: int
    budget: int | None
    max_age_days: int | None

    @property
    def over_budget(self) -> bool:
        return self.budget is not None and self.installed_bytes + self.download_bytes > self.budget

    @property
    def to_fetch(self) -> list[Item]:
        return [i for i in self.items if i.action in {"install", "update"}]

    @property
    def problems(self) -> list[Item]:
        return [i for i in self.items if i.action in {"blocked", "unavailable"}]

    def as_dict(self) -> dict[str, Any]:
        return {
            "manifest": str(self.manifest) if self.manifest else None,
            "items": [{k: v for k, v in i.__dict__.items() if k != "entry"} for i in self.items],
            "extras": self.extras,
            "download_bytes_approx": self.download_bytes,
            "download_note": "approximate: the catalogue's rounded lengths; the .meta4 has the exact size",
            "installed_bytes": self.installed_bytes,
            "budget": self.budget,
            "over_budget": self.over_budget,
            "max_age_days": self.max_age_days,
        }


def wanted_names(libraries: tuple[str, ...], named_groups: tuple[str, ...]) -> list[str]:
    """Manifest libraries first, then each group's members, each name once."""
    names: dict[str, None] = dict.fromkeys(libraries)
    for group in named_groups:
        if group not in groups.GROUPS:
            raise ZimloreError(f"unknown group {group!r}", f"the groups are {sorted(groups.GROUPS)}")
        names.update(dict.fromkeys(groups.GROUPS[group]))
    return list(names)


def make_plan(
    manifest: Manifest,
    extra_groups: tuple[str, ...] = (),
    *,
    update: bool = False,
    today: date | None = None,
) -> Plan:
    """Compare the manifest with what is installed and with the catalogue. Reads the catalogue (one query per
    name, for sizes and dates) and the local library; downloads and writes nothing."""
    names = wanted_names(manifest.libraries, (*manifest.groups, *extra_groups))
    today = today or datetime.now(UTC).date()
    scanned = library.scan()
    directory = library.zim_dirs()[0]
    items: list[Item] = []
    for name in names:
        mine = [b for b in scanned.books if b.name == name]
        newest_book = library.newest(mine)
        have = newest_book.date if newest_book else ""
        newest = catalog.latest(catalog.editions_of(name))
        item = Item(name, "unavailable", installed=have or None)
        if newest_book is not None:
            age = newest_book.age_days(today)
            item.over_max_age = bool(manifest.max_age_days and age is not None and age > manifest.max_age_days)
        if not newest:
            item.note = "the catalogue has no entry with this name"
            if mine:
                item.action, item.note = "unlisted", item.note + "; the installed edition is kept"
            items.append(item)
            continue
        entry = newest[0]
        item.available, item.entry, item.file = entry.date, entry, catalog.target_name(entry)
        if not mine:
            item.action = "install"
        elif (newer := library.is_newer(entry.date, have)) is not False:
            item.action = "update" if update else "outdated"
            item.note = "" if update else "newer edition available; --update stages it beside the installed one"
            if newer is None:
                item.note = "the installed edition has no usable Date, so it may be older; " + item.note
        else:
            item.action = "current"
        if item.action in {"install", "update"}:
            item.approx_bytes = entry.approx_bytes
            if os.path.lexists(directory / item.file):
                item.action, item.approx_bytes = "blocked", 0
                item.note = (
                    f"{item.file} is already in {directory} but is not a readable edition of {name}; move it aside"
                )
        items.append(item)
    present = {b.name for b in scanned.books}
    extras = [
        {
            "name": n,
            "editions": sum(b.name == n for b in scanned.books),
            "bytes": sum(b.size for b in scanned.books if b.name == n),
        }
        for n in sorted(present - set(names))
    ]
    return Plan(
        manifest.path,
        items,
        extras,
        sum(i.approx_bytes for i in items),
        sum(b.size for b in scanned.books),
        manifest.budget,
        manifest.max_age_days,
    )


def execute(plan: Plan, *, progress: Callable[[str, int, int], None] | None = None) -> list[dict[str, Any]]:
    """Download what the plan says to fetch. Refuses (before the first byte) when the plan exceeds the budget.
    One failed library does not stop the others: each outcome is reported, and the caller exits non-zero."""
    if plan.over_budget:
        raise ZimloreError(
            f"the sync would grow the library to about {(plan.installed_bytes + plan.download_bytes) / 1e6:.1f} MB "
            f"({plan.installed_bytes / 1e6:.1f} MB installed + about {plan.download_bytes / 1e6:.1f} MB new), "
            f"over the {(plan.budget or 0) / 1e6:.1f} MB budget; nothing was downloaded",
            "raise `budget` in the manifest, drop a library or group, or free space: zimlore prune --yes",
        )
    directory = library.zim_dirs()[0]
    library.close_all()
    results: list[dict[str, Any]] = []
    for item in plan.to_fetch:
        if item.entry is None:
            continue
        name = item.name

        def report(done: int, total: int, name: str = name) -> None:
            if progress:
                progress(name, done, total)

        try:
            path = catalog.download(item.entry, directory, progress=report, added_by="sync")
        except ZimloreError as error:
            results.append(
                {"name": name, "action": item.action, "ok": False, "error": error.message, "hint": error.hint}
            )
            continue
        results.append({"name": name, "action": item.action, "ok": True, "file": str(path)})
    return results
