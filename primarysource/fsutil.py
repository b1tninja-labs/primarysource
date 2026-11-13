"""Filesystem helpers that behave the same on Windows, macOS and Linux: atomic write, sha256, a write lock.

Lifted from rfclib's `fsutil.py` (`atomic_write_bytes`, `bulk_lock`) and zimlore's `catalog.py::_acquire_lock`.

- `atomic_write`: a temp file in the destination directory, then `os.replace`, so a reader never sees half a file
  and a crash leaves no torn one. On Windows `os.replace` fails while another process holds the target open
  (antivirus, search indexers, a concurrent reader), so it retries briefly.
- `write_lock`: an `O_EXCL` lock file, which works on every OS and on network filesystems. A lock whose last touch
  is older than `stale_after` belonged to a process that died, and is taken over. A long holder calls
  `Lock.touch()` as it works so it is never mistaken for a dead one.
- `bulk_lock`: one long-running writer per library (`<home>/.write.lock`); short writes rely on SQLite's locking.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError

STALE_LOCK_SECONDS = 6 * 3600
REPLACE_RETRIES = 10
CHUNK = 1 << 20


def replace(
    source: Path, target: Path, retries: int = REPLACE_RETRIES, sleep: Callable[[float], None] = time.sleep
) -> None:
    """`os.replace(source, target)`, retried while Windows reports the target in use."""
    for attempt in range(retries):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            sleep(0.05 * (attempt + 1))


def atomic_write(path: Path, data: bytes) -> None:
    """Write `data` to `path` through a temp file in the same directory and `os.replace`.

    A reader sees the old file or the new one, never a partial one. itulib's index rebuild unlinks first and a
    concurrent reader then sees "no index"; this is the replacement for that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        replace(Path(temp_name), path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def sha256(data: bytes) -> str:
    """The lowercase hex sha256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """The lowercase hex sha256 of the file at `path`, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class LockHeld(LibError):
    """Another live process holds the lock."""


@dataclass(frozen=True)
class Lock:
    """A held lock. `touch()` marks the holder alive; a failed touch only risks the lock being called stale."""

    path: Path

    def touch(self) -> None:
        with contextlib.suppress(OSError):
            os.utime(self.path)


def _create(lock: Path) -> int | None:
    try:
        return os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None


@contextlib.contextmanager
def write_lock(
    lock: Path,
    *,
    stale_after: float = STALE_LOCK_SECONDS,
    what: str = "this library",
    clock: Callable[[], float] = time.time,
) -> Iterator[Lock]:
    """Hold the lock file `lock` (created with `O_EXCL`) for the body, and remove it after.

    A lock untouched for more than `stale_after` seconds is taken over. A younger one raises `LockHeld`, naming
    the holder the lock file records. Two processes that find the same stale lock at the same instant can both
    take it over; after `stale_after` seconds of silence that window is accepted, as rfclib accepted it.
    """
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    for _ in range(3):
        descriptor = _create(lock)
        if descriptor is not None:
            break
        try:
            age = clock() - lock.stat().st_mtime
        except OSError:
            continue  # removed between the create and the stat: try again
        if age <= stale_after:
            holder = ""
            with contextlib.suppress(OSError):
                holder = lock.read_text("utf-8").strip()
            raise LockHeld(
                f"another process is writing {what} ({holder or 'holder unknown'}; lock {lock})",
                f"wait for it to finish; if none is running, delete {lock}",
            )
        with contextlib.suppress(OSError):
            lock.unlink()  # stale: its holder died
    if descriptor is None:
        raise LockHeld(f"could not take {lock}", f"if no other process is running, delete {lock}")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"pid {os.getpid()} since {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        yield Lock(lock)
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


@contextlib.contextmanager
def bulk_lock(home: Path, name: str = "write", *, stale_after: float = STALE_LOCK_SECONDS) -> Iterator[Lock]:
    """One long-running writer per library (init, sync, index build): the lock `<home>/.<name>.lock`."""
    with write_lock(home / f".{name}.lock", stale_after=stale_after, what=str(home)) as held:
        yield held
