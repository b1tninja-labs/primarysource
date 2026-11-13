"""Filesystem helpers that behave the same on Windows, macOS and Linux.

atomic_write_bytes: write to a temp file in the destination directory, then
os.replace() it into place, so a reader (another MCP server process, the
reader UI) never sees a half-written RFC and a crash leaves no torn file.
On Windows os.replace fails while another process holds the target open
(antivirus, search indexers, a concurrent reader), so it retries briefly.

bulk_lock: one long-running writer at a time per library (init, sync,
index build). Short writes such as on-demand indexing of a single RFC rely
on SQLite's own locking (busy_timeout) instead.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

STALE_LOCK_SECONDS = 6 * 3600


def atomic_write_bytes(dest: Path, data: bytes, retries: int = 10) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    for attempt in range(retries):
        try:
            os.replace(tmp, dest)
            return
        except PermissionError:
            if attempt == retries - 1:
                with contextlib.suppress(OSError):
                    tmp.unlink()
                raise
            time.sleep(0.05 * (attempt + 1))


class LockHeld(RuntimeError):
    pass


@contextlib.contextmanager
def bulk_lock(home: Path, name: str = "write"):
    """Exclusive lock file <home>/.<name>.lock (O_EXCL create, works on every
    OS and on network filesystems). A lock older than STALE_LOCK_SECONDS is
    taken over: its holder crashed."""
    home.mkdir(parents=True, exist_ok=True)
    lock = home / f".{name}.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue
            if age > STALE_LOCK_SECONDS:
                with contextlib.suppress(OSError):
                    lock.unlink()
                continue
            holder = ""
            with contextlib.suppress(OSError):
                holder = lock.read_text("utf-8").strip()
            raise LockHeld(f"another rfclib process is updating this library "
                           f"({holder or lock}); wait for it to finish") \
                from None
    else:
        raise LockHeld(f"could not take {lock}")
    try:
        os.write(fd, f"pid {os.getpid()} since {time.strftime('%H:%M:%S')}"
                 .encode())
        os.close(fd)
        yield lock
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()
