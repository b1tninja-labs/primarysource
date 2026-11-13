"""The core filesystem helpers: atomic write with retry, sha256, and the O_EXCL write lock."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from primarysource import fsutil
from primarysource.fsutil import LockHeld, atomic_write, bulk_lock, sha256, sha256_file, write_lock
from primarysource.home import atomic_write as home_atomic_write


def test_atomic_write_is_the_one_home_re_exports(tmp_path: Path) -> None:
    assert home_atomic_write is atomic_write
    target = tmp_path / "a" / "b.bin"
    atomic_write(target, b"one")
    atomic_write(target, b"two")
    assert target.read_bytes() == b"two"
    assert [p.name for p in target.parent.iterdir()] == ["b.bin"]


def test_replace_retries_while_the_target_is_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, target = tmp_path / "s", tmp_path / "t"
    source.write_bytes(b"new")
    real = os.replace
    calls: list[int] = []

    def flaky(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("held by another process")
        real(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    sleeps: list[float] = []
    fsutil.replace(source, target, sleep=sleeps.append)
    assert target.read_bytes() == b"new"
    assert len(sleeps) == 2
    source.write_bytes(b"again")
    calls.clear()
    with pytest.raises(PermissionError):
        fsutil.replace(source, target, retries=2, sleep=sleeps.append)


def test_sha256_of_bytes_and_of_a_file(tmp_path: Path) -> None:
    data = b"invented bytes" * 100_000
    path = tmp_path / "f"
    path.write_bytes(data)
    assert sha256(data) == sha256_file(path) == hashlib.sha256(data).hexdigest()


def test_a_held_lock_refuses_a_second_writer_and_names_the_holder(tmp_path: Path) -> None:
    with bulk_lock(tmp_path) as held:
        assert held.path == tmp_path / ".write.lock"
        assert f"pid {os.getpid()}" in held.path.read_text("utf-8")
        with pytest.raises(LockHeld) as refused, bulk_lock(tmp_path):
            pass
        assert f"pid {os.getpid()}" in refused.value.message
        assert str(held.path) in refused.value.hint
    assert not (tmp_path / ".write.lock").exists()


def test_a_stale_lock_is_taken_over(tmp_path: Path) -> None:
    lock = tmp_path / ".write.lock"
    lock.write_text("pid 1 since long ago", "utf-8")
    old = lock.stat().st_mtime - 7 * 3600
    os.utime(lock, (old, old))
    with bulk_lock(tmp_path) as held:
        assert f"pid {os.getpid()}" in held.path.read_text("utf-8")
    assert not lock.exists()


def test_touch_keeps_a_long_holder_from_looking_stale(tmp_path: Path) -> None:
    lock = tmp_path / "x.part.lock"
    with write_lock(lock, stale_after=60) as held:
        old = lock.stat().st_mtime - 3600
        os.utime(lock, (old, old))
        held.touch()
        with pytest.raises(LockHeld), write_lock(lock, stale_after=60):
            pass


def test_the_lock_is_released_when_the_body_fails(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), bulk_lock(tmp_path, "index"):
        raise RuntimeError("boom")
    assert not (tmp_path / ".index.lock").exists()
