"""Managing what is installed: provenance sidecars, verify, remove, prune, du.

No network here (that is `catalog.py`). Every function takes the library directories from `library.zim_dirs()`
and only ever deletes files it found by scanning them: a path typed by a user is never passed to `unlink`.

**Provenance.** Each installed ZIM may have a sidecar `<file>.zimlore.json` recording where it came from and the
SHA-256 it had when it was verified. It is data, not trust: a file without one is `provenance: unknown`, and a
sidecar written by `verify --adopt` says `added_by: adopt`, leaves `catalogue_name`, `catalogue_date` and
`fetched_at` empty (nothing observed them) and records only what the file *is* now plus `adopted_at`.

**Deleting.** An edition is a ZIM `uuid`: copies of one uuid in two directories are one edition, and two uuids
sharing a Name and Date are an ambiguity that `remove` and `prune` report and refuse. Editions are ordered by the
PARSED `Date`; a group with a date that does not parse is never pruned. `prune` deletes only zimlore-managed files
(`added_by` get, sync or add) unless told `include_unmanaged`, refuses to delete anything while an edition it
keeps fails verification, and every deleting function returns what it deleted AND what failed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any

from . import library
from .errors import ZimloreError
from .library import Book

SIDECAR_SUFFIX = ".zimlore.json"
SCHEMA = 1
MANAGED = frozenset({"get", "sync", "add"})
"""`added_by` values that mean zimlore itself put the file here. `adopt` and no sidecar at all do not."""
QUIET_SECONDS = 600
"""A `*.zim.part` or `*.zimlore.json.tmp` modified within the last ten minutes may belong to a live download or
write, so `prune` and `du` leave it alone (as they do a `.part` with a `.part.lock`)."""


@dataclass(frozen=True)
class Provenance:
    source: str  # the URL the bytes came from, "" when unknown
    catalogue_name: str
    catalogue_date: str
    sha256: str
    size: int
    fetched_at: str
    added_by: str  # "get" | "add" | "sync" | "adopt"
    schema: int = SCHEMA
    adopted_at: str = ""  # only `verify --adopt` sets it: when zimlore first saw the file


def sidecar_path(zim: Path) -> Path:
    return zim.with_name(zim.name + SIDECAR_SUFFIX)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def hash_and_size(path: Path) -> tuple[str, int]:
    """SHA-256 and size from ONE open handle: the size is the bytes hashed, and a file whose length changed while
    it was read is an error, so a sidecar can never pair one file's size with another's hash."""
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            total += len(chunk)
        end = os.fstat(handle.fileno()).st_size
    if end != total:
        raise ZimloreError(
            f"{path} changed while it was being read", "run the command again when nothing writes to it"
        )
    return digest.hexdigest(), total


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_sidecar(zim: Path, record: Provenance) -> Path:
    """Write the sidecar through a temporary file that is flushed to disk before it replaces the old one."""
    path = sidecar_path(zim)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(record), indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return path


def read_sidecar(zim: Path) -> tuple[Provenance | None, str]:
    """(record, problem). `(None, "")` means there is no sidecar; a sidecar that cannot be used is reported in
    `problem` rather than treated as absent, because a corrupt record is not the same as no record."""
    path = sidecar_path(zim)
    if not path.is_file():
        return None, ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
            return None, f"{path.name}: unknown schema {raw.get('schema') if isinstance(raw, dict) else raw!r}"
        return Provenance(**raw), ""
    except (OSError, ValueError, TypeError) as error:
        return None, f"{path.name}: {error}"


def provenance_summary(zim: Path) -> dict[str, Any]:
    """What an agent or a citation may say about where a file came from."""
    record, problem = read_sidecar(zim)
    if record is None:
        return {"state": "unrecorded" if not problem else "unreadable", "note": problem or "no sidecar"}
    summary: dict[str, Any] = {
        "state": "recorded",
        "source": record.source or None,
        "sha256": record.sha256,
        "fetched_at": record.fetched_at or None,  # an adopted file was never fetched by zimlore
        "added_by": record.added_by,
    }
    if record.adopted_at:
        summary["adopted_at"] = record.adopted_at
    return summary


# --- verify --------------------------------------------------------------------------------------------------


def _selected(name: str) -> list[Book]:
    scanned = library.scan()
    if not scanned.books and not scanned.problems:
        raise library.empty_library_error(scanned)
    if not name:
        return scanned.books
    wanted = library.select(name, scanned)
    if wanted.kind == "newest":  # a family named without a version: check every version of it
        return list(wanted.members)
    return [b for b in scanned.books if b.name == wanted.book.name]


def verify(name: str = "", *, hash_files: bool = True, adopt: bool = False) -> dict[str, Any]:
    """Check installed files against their sidecars and libzim's own checksum.

    status per file: `ok` (sidecar matches and libzim's checksum holds), `changed` (size or SHA-256 differs from
    the sidecar), `corrupt` (libzim's checksum fails), `unrecorded` (no sidecar; the file is only integrity-checked),
    `adopted` (a sidecar was written because `adopt` was set), `adopted-unchecked` (the same, but the ZIM carries no
    checksum of its own, so nothing vouches for it). `unreadable` files are listed by the scan itself.
    """
    rows: list[dict[str, Any]] = []
    for book in _selected(name):
        record, problem = read_sidecar(book.path)
        archive = library.open_archive(book.path)
        intact = bool(archive.check()) if archive.has_checksum else None
        row: dict[str, Any] = {"name": book.name, "edition": book.date or None, "file": book.path.name}
        if record is None:
            row["status"] = "corrupt" if intact is False else "unrecorded"
            if problem:
                row["provenance_problem"] = problem
            if adopt and intact is not False and not problem:
                digest, size = hash_and_size(book.path)
                write_sidecar(book.path, Provenance("", "", "", digest, size, "", "adopt", adopted_at=now()))
                row["status"] = "adopted" if intact else "adopted-unchecked"
                if intact is None:
                    row["note"] = "this ZIM has no checksum of its own: only the hash recorded now can vouch for it"
        else:
            if hash_files:
                actual, size = hash_and_size(book.path)
            else:
                actual, size = "", book.path.stat().st_size
            if size != record.size:
                row["status"], row["why"] = "changed", f"size {size} != recorded {record.size}"
            elif hash_files and actual != record.sha256:
                row["status"], row["why"] = "changed", f"sha256 {actual[:12]}... != recorded {record.sha256[:12]}..."
            elif intact is False:
                row["status"], row["why"] = "corrupt", "libzim's own checksum fails"
            else:
                row["status"] = "ok"
            if not hash_files and row["status"] == "ok":
                row["note"] = "size only; SHA-256 not recomputed"
        row["libzim_checksum"] = intact
        rows.append(row)
    problems = library.scan().problems  # a file libzim cannot open at all (truncated, trailing bytes) is a failure
    bad = [r for r in rows if r["status"] in {"changed", "corrupt"}]
    return {"files": rows, "problems": problems, "failed": len(bad) + len(problems)}


# --- editions ------------------------------------------------------------------------------------------------


@dataclass
class Edition:
    """One ZIM (one `uuid`) and every installed copy of it."""

    uuid: str
    books: list[Book] = field(default_factory=list)

    @property
    def date_text(self) -> str:
        return self.books[0].date

    @property
    def when(self) -> date | None:
        return self.books[0].when


def editions_of(books: list[Book]) -> list[Edition]:
    """Group files by `uuid` (copies in two directories are one edition) and order them newest first by parsed
    date, undated last. Ties are broken by uuid only to be deterministic: callers refuse ties before acting."""
    grouped: dict[str, Edition] = {}
    for book in sorted(books, key=lambda b: str(b.path)):
        grouped.setdefault(book.uuid, Edition(book.uuid)).books.append(book)
    return sorted(grouped.values(), key=lambda e: (library.date_key(e.date_text), e.uuid), reverse=True)


def _managed(book: Book) -> bool:
    record, _ = read_sidecar(book.path)
    return record is not None and record.added_by in MANAGED


def _health(book: Book) -> str:
    """'' when the file passes every check available to it, else why not: libzim's checksum and, when a sidecar
    exists, its size and SHA-256. A file nothing can vouch for is not healthy: it is 'unverifiable'."""
    try:
        archive = library.open_archive(book.path)
        record, _ = read_sidecar(book.path)
        checks = 0
        if archive.has_checksum:
            if not archive.check():
                return "fails libzim's own checksum"
            checks += 1
        if record is not None:
            digest, size = hash_and_size(book.path)
            if size != record.size or digest != record.sha256:
                return "no longer matches its provenance record"
            checks += 1
    except (OSError, ZimloreError) as error:
        return f"cannot be checked ({error})"
    return "" if checks else "cannot be verified: it has no checksum of its own and no provenance record"


def _failure(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return "stop any running 'zimlore mcp' server or kiwix reader that has it open, then retry"
    return ""


def _delete(book: Book) -> int:
    """Delete one edition file and its sidecar; return the bytes freed. Raises `OSError` (a `FileNotFoundError` for
    a file that is already gone). The sidecar goes FIRST, so a later file of the same name can never inherit it;
    if the ZIM then cannot be deleted (Windows keeps it locked while a handle is open) the sidecar is put back."""
    library.close_path(book.path)
    sidecar = sidecar_path(book.path)
    try:
        saved: bytes | None = sidecar.read_bytes()
    except FileNotFoundError:
        saved = None
    if saved is not None:
        sidecar.unlink()
    try:
        book.path.unlink()
    except FileNotFoundError:
        raise
    except OSError:
        if saved is not None:
            sidecar.write_bytes(saved)
        raise
    return book.size


def _unlink_leftover(path: Path, size: int) -> int:
    path.unlink()
    return size


def _unlink_all(
    books: list[Book], leftovers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Delete each file on its own: a file that vanished is success, any other `OSError` is recorded and the rest
    still go. Returns (deleted, failed, bytes freed)."""
    deleted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    freed = 0
    work: list[tuple[Path, int, Callable[[], int]]] = [(b.path, b.size, partial(_delete, b)) for b in books]
    for item in leftovers:
        path, size = Path(item["file"]), int(item["bytes"])
        work.append((path, size, partial(_unlink_leftover, path, size)))
    for path, size, action in work:
        try:
            freed += action()
            deleted.append({"file": str(path), "bytes": size})
        except FileNotFoundError:
            deleted.append({"file": str(path), "bytes": 0, "already_gone": True})
        except OSError as error:
            failed.append({"file": str(path), "error": str(error), "hint": _failure(error)})
    return deleted, failed, freed


def _result(
    plan: list[dict[str, Any]],
    applied: bool,
    outcome: tuple[list[dict[str, Any]], list[dict[str, Any]], int],
    refused: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    deleted, failed, freed = outcome
    note = ""
    if failed:
        note = f"{len(failed)} file(s) could NOT be deleted and {len(deleted)} were; see 'failed'"
    elif not applied and plan:
        note = "dry run: nothing was deleted; add --yes to delete"
    return {
        "applied": applied,
        "files": plan,
        "deleted": deleted,
        "failed": failed,
        "refused": refused,
        "skipped": skipped,
        "bytes": sum(item["bytes"] for item in plan),
        "freed": freed,
        "ok": not failed and not (applied and refused),
        "note": note,
    }


def _plan_item(book: Book) -> dict[str, Any]:
    return {"file": str(book.path), "edition": book.date or None, "uuid": book.uuid, "bytes": book.size}


def _leftovers(
    directories: list[Path], *, everywhere: bool = False, moment: float | None = None
) -> list[dict[str, Any]]:
    """Files zimlore itself leaves behind: `*.zim.part` (an interrupted download) and `*.zimlore.json.tmp` (a
    sidecar write that died). Only regular files, never a symlink or directory, never one touched in the last
    `QUIET_SECONDS`, never a `.part` with a `.part.lock`, and by default only in the directory zimlore
    downloads to."""
    moment = time.time() if moment is None else moment
    found: list[dict[str, Any]] = []
    for directory in directories if everywhere else directories[:1]:
        if not directory.is_dir():
            continue
        for pattern, kind in (("*.zim.part", "partial download"), ("*.zimlore.json.tmp", "stale sidecar temp file")):
            for path in sorted(directory.glob(pattern)):
                if path.is_symlink() or not path.is_file():
                    continue
                if kind == "partial download" and path.with_name(path.name + ".lock").exists():
                    continue
                stat = path.stat()
                if moment - stat.st_mtime < QUIET_SECONDS:
                    continue
                found.append({"file": str(path), "edition": None, "bytes": stat.st_size, "kind": kind})
    return found


# --- remove / prune / du -------------------------------------------------------------------------------------


def _edition_matches(edition: Edition, text: str) -> bool:
    wanted = library.parse_date(text)
    return text in {edition.uuid, edition.date_text} or (wanted is not None and wanted == edition.when)


def remove(
    name: str, *, edition: str = "", all_editions: bool = False, all_versions: bool = False, apply: bool = False
) -> dict[str, Any]:
    """Remove installed editions of one library. Dry run unless `apply`. With several editions installed the
    caller must say which (`edition`: a date or a uuid) or say all (`all_editions`): deleting a user's files is
    never a default. Two different ZIMs sharing the date are an ambiguity, not a pair to delete together. The
    result lists `deleted` and `failed` files even when some deletions fail.

    A name that means a package with several installed VERSIONS (`cobra`) is refused unless a version is written
    (`cobra v1.8.1`) or `all_versions` says every version goes: 'the newest' is a fine thing to read and a
    surprising thing to delete."""
    scanned = library.scan()
    if not scanned.books:
        raise library.empty_library_error(scanned)
    selected = library.select(name, scanned)
    chosen = selected.book
    if all_versions:
        found = editions_of(list(selected.members))
    elif selected.kind == "newest" and selected.other_versions:
        raise ZimloreError(
            f"{chosen.family} has {len(selected.versions)} versions installed; say which to remove",
            f"write the version (remove '{chosen.family} {chosen.version}'), or --all-versions for every one",
            versions=selected.versions,
        )
    else:
        found = editions_of(library.editions(chosen, scanned.books))
    if edition:
        matching = [e for e in found if _edition_matches(e, edition)]
        if not matching:
            raise ZimloreError(f"{chosen.name} has no edition {edition}", "zimlore list shows the installed dates")
        if len(matching) > 1:
            raise ZimloreError(
                f"{len(matching)} different ZIMs of {chosen.name} carry the date {edition}; not guessing",
                "name one by its uuid: --edition UUID (candidates are listed); the files are different builds",
                candidates=[{"uuid": e.uuid, "files": [str(b.path) for b in e.books]} for e in matching],
            )
        found = matching
    elif len(found) > 1 and not (all_editions or all_versions):
        raise ZimloreError(
            f"{chosen.name} has {len(found)} editions installed; say which to remove",
            "--edition DATE for one, --all to remove every edition",
            editions=[e.date_text for e in found],
        )
    books = [b for e in found for b in e.books]
    plan = [_plan_item(b) for b in books]
    outcome = _unlink_all(books, []) if apply else ([], [], 0)
    return {"name": chosen.name, **_result(plan, apply, outcome, [], [])}


def prune(
    *, keep: int = 2, apply: bool = False, include_unmanaged: bool = False, moment: float | None = None
) -> dict[str, Any]:
    """Delete all but the newest `keep` editions of every library, and zimlore's own stale leftovers. Dry run
    unless `apply`.

    Refuses (and says why, under `refused`) any library whose editions cannot be ordered safely: a `Date` that does
    not parse, or two different ZIMs sharing one, and any library where an edition it would KEEP fails verification
    (libzim's checksum, the sidecar hash), because the older edition may be the only good copy. Files zimlore did not
    put there (no sidecar, or `added_by: adopt`) are listed under `skipped` and kept unless `include_unmanaged`."""
    if keep < 1:
        raise ZimloreError("keep must be at least 1", "pruning every edition is `zimlore remove --all`")
    scanned = library.scan()
    doomed: list[Book] = []
    refused: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for name in sorted({b.name for b in scanned.books}):
        found = editions_of([b for b in scanned.books if b.name == name])
        if len(found) <= keep:
            continue
        files = [str(b.path) for e in found for b in e.books]
        undated = [e for e in found if e.when is None]
        if undated:
            refused.append(
                {
                    "name": name,
                    "reason": "an edition has no Date that parses, so its age is unknown and nothing is deleted",
                    "files": [str(b.path) for e in undated for b in e.books],
                }
            )
            continue
        dates = [e.when for e in found]
        if len(set(dates)) != len(dates):
            refused.append(
                {
                    "name": name,
                    "reason": "two different ZIMs (different uuid) share a Name and Date; which is older is unknown",
                    "files": files,
                }
            )
            continue
        broken = None
        for edition in found[:keep]:
            results = [(b, _health(b)) for b in edition.books]
            if all(why for _, why in results):
                broken = results[0]
                break
        if broken is not None:
            refused.append(
                {
                    "name": name,
                    "reason": f"{broken[0].path} is kept but {broken[1]}; the older one may be the last good copy",
                    "files": [str(broken[0].path)],
                }
            )
            continue
        for edition in found[keep:]:
            for book in edition.books:
                if include_unmanaged or _managed(book):
                    doomed.append(book)
                else:
                    skipped.append(
                        {
                            **_plan_item(book),
                            "reason": "not installed by zimlore; --include-unmanaged deletes it",
                        }
                    )
    leftovers = _leftovers(scanned.directories, everywhere=include_unmanaged, moment=moment)
    plan = [_plan_item(b) for b in doomed] + leftovers
    outcome = _unlink_all(doomed, leftovers) if apply else ([], [], 0)
    result = {"keep": keep, **_result(plan, apply, outcome, refused, skipped)}
    if refused and not result["note"]:
        result["note"] = f"{len(refused)} library(ies) were not pruned; see 'refused'"
    elif skipped and not result["note"]:
        result["note"] = f"{len(skipped)} file(s) were left alone because zimlore did not install them; see 'skipped'"
    return result


def du() -> dict[str, Any]:
    """Disk use per library (all editions), partial downloads, and free space on the volume. Partial downloads are
    counted by the same rule `prune` deletes them by: stale `*.zim.part` regular files without a live lock."""
    scanned = library.scan()
    per: dict[str, dict[str, Any]] = {}
    for name in sorted({b.name for b in scanned.books}):
        mine = [b for b in scanned.books if b.name == name]
        newest = library.newest(mine)
        per[name] = {
            "name": name,
            "editions": len(editions_of(mine)),
            "bytes": sum(b.size for b in mine),
            "newest": newest.date if newest else "",
        }
    leftovers = _leftovers(scanned.directories)
    partial = sum(item["bytes"] for item in leftovers if item["kind"] == "partial download")
    where = next((d for d in scanned.directories if d.exists()), None)
    free = shutil.disk_usage(where).free if where else None
    libraries = sorted(per.values(), key=lambda r: -r["bytes"])
    return {
        "libraries": libraries,
        "total_bytes": sum(r["bytes"] for r in libraries),
        "partial_bytes": partial,
        "stale_temp_files": sum(item["kind"] != "partial download" for item in leftovers),
        "free_bytes": free,
        "directories": [str(d) for d in scanned.directories],
    }


# --- add -----------------------------------------------------------------------------------------------------


def _copy_hashed(source: Path, target: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("wb") as writer:
        while chunk := reader.read(1 << 20):
            writer.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def add_local(source: Path, *, link: bool = False, force: bool = False) -> dict[str, Any]:
    """Install a local ZIM into the first library directory, with a provenance sidecar (`added_by: add`).

    libzim opens the file first, so an unreadable file is an error with nothing copied; its own checksum must
    hold unless `force`. The file is copied by default (safe on Windows, no dangling links, no lock on the
    original); `link` makes a hard link, then a symbolic link, and says so when the OS refuses both. An existing
    file at the target is never overwritten: an identical one means "already installed", a different one is an
    error. Two files carrying one Name and Date are the same edition, so the second is refused naming `remove`.
    """
    source = source.expanduser()
    if not source.is_file():
        raise ZimloreError(f"{source} is not a file", "give the path of a .zim file")
    if source.suffix != ".zim":
        raise ZimloreError(f"{source} does not end in .zim", "zimlore add takes a .zim file")
    library.close_all()
    try:
        book = library.read_book(source)
        archive = library.open_archive(source)
        intact = bool(archive.check()) if archive.has_checksum else None
    except ZimloreError as error:
        raise ZimloreError(
            error.message, "nothing was copied; check that the file is a complete .zim (re-download or re-copy it)"
        ) from error
    finally:
        library.close_all()  # Windows keeps the file locked while a handle is open
    if intact is False and not force:
        raise ZimloreError(
            f"{source} fails libzim's own checksum: the file is damaged",
            "nothing was copied; re-obtain the file, or --force to install it anyway (verify will keep flagging it)",
        )
    directory = library.zim_dirs()[0]
    if source.resolve().parent in {d.resolve() for d in library.zim_dirs() if d.is_dir()}:
        raise ZimloreError(
            f"{source} is already in the library directory {source.parent}",
            "nothing to add; zimlore verify --adopt records a provenance sidecar for it",
        )
    target = directory / source.name
    base = {"name": book.name, "edition": book.date or None, "file": str(target)}
    if os.path.lexists(target):
        digest = sha256_of(source)
        if target.is_file() and sha256_of(target) == digest:
            return {**base, "status": "already-installed", "mode": "none", "bytes": book.size, "sha256": digest}
        raise ZimloreError(
            f"{target} already exists and is a different file; not overwriting it",
            "rename the source, or remove the installed file first: zimlore list shows it, zimlore remove deletes it",
        )
    clash = [b for b in library.scan().books if b.name == book.name and (b.date == book.date or b.uuid == book.uuid)]
    library.close_all()
    if clash:
        raise ZimloreError(
            f"{book.name} edition {book.date or 'undated'} is already installed as {clash[0].path.name}",
            f"replace it deliberately: zimlore remove {book.name} --edition {book.date} --yes, then add again",
        )
    directory.mkdir(parents=True, exist_ok=True)
    if link:
        digest = sha256_of(source)
        mode = "hardlink"
        try:
            os.link(source, target)
        except OSError:
            mode = "symlink"
            try:
                os.symlink(source.resolve(), target)
            except OSError as error:
                raise ZimloreError(
                    f"the operating system refused both a hard link and a symbolic link to {source} ({error})",
                    "omit --link to copy the file instead",
                ) from error
    else:
        mode = "copy"
        staged = target.with_name(target.name + ".add.part")
        try:
            digest = _copy_hashed(source, staged)
            os.replace(staged, target)
        except OSError as error:
            staged.unlink(missing_ok=True)
            raise ZimloreError(
                f"could not copy {source} to {target} ({error})", "free disk space and retry"
            ) from error
    size = target.stat().st_size
    write_sidecar(target, Provenance(str(source.resolve()), book.name, book.date, digest, size, now(), "add"))
    return {
        **base,
        "status": "added",
        "mode": mode,
        "bytes": size,
        "sha256": digest,
        "checksum": intact,
        "forced": bool(force and intact is False),
    }
