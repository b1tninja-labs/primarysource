"""What `remove`, `prune`, `du`, `verify --adopt` and the handle cache must NOT do to a user's files.

Each test pins one finding of the independent review (A1-A9 and the handle cache); the docstring of the
behaviour is in `zimlore/manage.py`."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from zimfixture import age, build_zim, managed

from primarysource.zim import cli, library, manage
from primarysource.zim.errors import ZimloreError


def _names(result: dict[str, Any]) -> list[str]:
    return sorted(Path(item["file"]).name for item in result["files"])


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(list(argv))
    return code, capsys.readouterr().out


def _flip(path: Path) -> None:
    library.close_all()
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def _editions(home: Path, *dates: str, sidecar: bool = True) -> list[Path]:
    made = []
    for date in dates:
        zim = build_zim(home / "zim", f"e_{date}.zim", date=date)
        made.append(managed(zim) if sidecar else zim)
    return made


# --- A1: ordering -------------------------------------------------------------------------------------------


def test_dates_are_parsed_loosely_and_never_guessed() -> None:
    assert str(library.parse_date("2026-9-15")) == "2026-09-15"
    assert str(library.parse_date("2026-10-01T03:00:00Z")) == "2026-10-01"
    for bad in ("", "autumn 2026", "2026-13-01", "2026-02-30", "26-10-01", "2026-10"):
        assert library.parse_date(bad) is None, bad
    assert library.is_newer("2026-10-01", "2026-9-15") is True and library.is_newer("", "2026-01-01") is None


def test_editions_and_prune_order_by_the_parsed_date_not_the_text(home: Path) -> None:
    sep, october = _editions(home, "2026-9-15", "2026-10-01")
    books = library.scan().books
    assert [b.date for b in library.editions(books[0], books)] == ["2026-10-01", "2026-9-15"]
    assert _names(manage.prune(keep=1)) == [sep.name]
    manage.prune(keep=1, apply=True)
    assert october.exists() and not sep.exists(), "as text '2026-9-15' sorts after '2026-10-01': the new file went"


def test_a_group_with_a_date_that_does_not_parse_is_never_pruned(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = _editions(home, "2026-06-01", "2026-08-01", "autumn 2026")
    for keep in (1, 2):
        result = manage.prune(keep=keep, apply=True)
        assert result["files"] == [] and result["deleted"] == [] and result["ok"] is False
        refused = result["refused"][0]
        assert refused["name"] == "acme_en_widgets" and "no Date that parses" in refused["reason"]
        assert refused["files"] == [str(files[2])]
    assert all(f.exists() for f in files)
    code, out = _cli(capsys, "prune", "--keep", "1", "--yes")
    assert code == 1 and "REFUSED" in out
    code, out = _cli(capsys, "prune", "--keep", "1")
    assert code == 0 and "REFUSED" in out, "a dry run explains but does not fail"


def test_an_undated_edition_alone_in_a_small_group_is_untouched(home: Path) -> None:
    files = _editions(home, "")
    assert manage.prune(keep=1, apply=True)["files"] == [] and files[0].exists()


# --- A2: verify what is kept --------------------------------------------------------------------------------


def test_prune_will_not_delete_the_good_edition_in_favour_of_a_corrupt_one(home: Path) -> None:
    good, bad = _editions(home, "2026-08-01", "2026-10-01")
    _flip(bad)
    result = manage.prune(keep=1, apply=True)
    assert good.exists() and bad.exists() and result["deleted"] == []
    assert bad.name in result["refused"][0]["reason"] and "libzim's own checksum" in result["refused"][0]["reason"]


def test_prune_checks_the_kept_edition_against_its_sidecar_too(home: Path) -> None:
    old, new = _editions(home, "2026-08-01", "2026-10-01")
    record, _ = manage.read_sidecar(new)
    assert record is not None
    manage.write_sidecar(new, dataclasses.replace(record, sha256="00" * 32))
    result = manage.prune(keep=1, apply=True)
    assert old.exists() and "provenance record" in result["refused"][0]["reason"]


def test_prune_refuses_when_a_kept_edition_cannot_be_verified_at_all(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = _editions(home, "2026-08-01", "2026-10-01")
    manage.sidecar_path(new).unlink()
    real = library.open_archive
    monkeypatch.setattr(library, "open_archive", lambda p: _NoChecksum(real(p)))
    result = manage.prune(keep=1, apply=True)
    assert old.exists() and "cannot be verified" in result["refused"][0]["reason"]


# --- A3: what counts as a leftover --------------------------------------------------------------------------


def test_only_stale_zimlore_part_files_are_swept_and_counted(home: Path) -> None:
    folder = home / "zim"
    stale = folder / "a_2026-10.zim.part"
    stale.write_bytes(b"s" * 100)
    age(stale)
    foreign = folder / "movie.mkv.part"
    foreign.write_bytes(b"f" * 13)
    age(foreign)
    young = folder / "b_2026-10.zim.part"
    young.write_bytes(b"y" * 7)
    locked = folder / "c_2026-10.zim.part"
    locked.write_bytes(b"l" * 11)
    age(locked)
    (folder / "c_2026-10.zim.part.lock").write_text("pid 1\n")
    directory = folder / "dir.zim.part"
    directory.mkdir()
    age(directory)
    assert manage.du()["partial_bytes"] == 100, "du counts by the rule prune deletes by"
    dry = manage.prune()
    assert _names(dry) == [stale.name]
    result = manage.prune(apply=True)
    assert result["failed"] == [] and result["freed"] == 100
    assert not stale.exists()
    assert all(p.exists() for p in (foreign, young, locked, directory))


# --- A4: partial application is reported, a vanished file is success --------------------------------------


def test_a_file_that_vanishes_during_prune_is_success_and_the_rest_still_go(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oldest, middle, newest = _editions(home, "2026-06-01", "2026-08-01", "2026-10-01")
    real = library.scan

    def racy(*args: Any, **kwargs: Any) -> library.Scan:
        scanned = real(*args, **kwargs)
        library.close_all()
        oldest.unlink()  # someone else deletes it between the scan and the delete
        return scanned

    monkeypatch.setattr(library, "scan", racy)
    result = manage.prune(keep=1, apply=True)
    assert result["failed"] == [] and result["ok"] is True
    assert sorted((Path(d["file"]).name, d.get("already_gone", False)) for d in result["deleted"]) == [
        (oldest.name, True),
        (middle.name, False),
    ]
    assert newest.exists() and not middle.exists() and not manage.sidecar_path(oldest).exists()


def _lock_file(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real = Path.unlink

    def locked(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == name:
            raise PermissionError(13, "in use by another process")
        real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)


def test_one_locked_file_is_reported_and_exit_1_while_the_others_are_deleted(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oldest, middle, newest = _editions(home, "2026-06-01", "2026-08-01", "2026-10-01")
    before = manage.sidecar_path(middle).read_text(encoding="utf-8")
    _lock_file(monkeypatch, middle.name)
    code, out = _cli(capsys, "prune", "--keep", "1", "--yes", "--json")
    result = json.loads(out)
    assert code == 1 and result["ok"] is False
    assert [Path(d["file"]).name for d in result["deleted"]] == [oldest.name]
    assert [Path(d["file"]).name for d in result["failed"]] == [middle.name]
    assert "primarysource zim mcp" in result["failed"][0]["hint"]
    assert not oldest.exists() and middle.exists() and newest.exists()
    assert manage.sidecar_path(middle).read_text(encoding="utf-8") == before, "the record of a kept file survives"


def test_remove_all_reports_what_was_deleted_before_a_failure(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, new = _editions(home, "2026-08-01", "2026-10-01")
    _lock_file(monkeypatch, old.name)
    result = manage.remove("acme", all_editions=True, apply=True)
    assert [Path(d["file"]).name for d in result["deleted"]] == [new.name] and result["freed"] > 0
    assert [Path(d["file"]).name for d in result["failed"]] == [old.name] and result["ok"] is False
    assert not new.exists() and old.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="only Windows locks a file that a reader has open")
def test_a_really_open_file_on_windows_is_a_reported_failure_not_a_traceback(home: Path) -> None:
    (zim,) = _editions(home, "2026-10-01")
    with zim.open("rb"):
        result = manage.remove("acme", apply=True)
    assert [Path(d["file"]).name for d in result["failed"]] == [zim.name] and zim.exists()
    assert manage.sidecar_path(zim).exists()


# --- A5: an edition is a uuid ---------------------------------------------------------------------------------


def test_copies_of_one_zim_in_two_directories_are_one_edition(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shelf = tmp_path / "shelf"
    shelf.mkdir()
    monkeypatch.setenv(library.PATH_ENV, os.pathsep.join([str(home / "zim"), str(shelf)]))
    old, new = _editions(home, "2026-08-01", "2026-10-01")
    twin = shelf / old.name
    shutil.copy2(old, twin)
    managed(twin)
    assert manage.prune(keep=2)["files"] == [], "two editions: the older one's two copies count once"
    assert sorted(i["file"] for i in manage.prune(keep=1)["files"]) == sorted([str(old), str(twin)])
    assert manage.du()["libraries"][0]["editions"] == 2
    removed = manage.remove("acme", edition="2026-08-01", apply=True)
    assert len(removed["deleted"]) == 2 and not old.exists() and not twin.exists() and new.exists()


def test_two_zims_sharing_a_name_and_date_are_an_ambiguity_remove_reports_and_refuses(home: Path) -> None:
    one = managed(build_zim(home / "zim", "t1.zim", date="2026-10-01"))
    two = managed(build_zim(home / "zim", "t2.zim", date="2026-10-01"))
    with pytest.raises(ZimloreError, match="different ZIMs") as caught:
        manage.remove("acme", edition="2026-10-01")
    candidates = cast("list[dict[str, Any]]", caught.value.extra["candidates"])
    assert len(candidates) == 2 and "--edition UUID" in caught.value.hint
    done = manage.remove("acme", edition=candidates[0]["uuid"], apply=True)
    assert len(done["deleted"]) == 1 and [one.exists(), two.exists()].count(True) == 1


def test_prune_refuses_a_library_whose_newest_dates_tie(home: Path) -> None:
    files = [
        managed(build_zim(home / "zim", f"t{n}.zim", date=day))
        for n, day in enumerate(["2026-10-01", "2026-10-01", "2026-08-01"])
    ]
    result = manage.prune(keep=1, apply=True)
    assert result["deleted"] == [] and "share a Name and Date" in result["refused"][0]["reason"]
    assert all(f.exists() for f in files)


# --- A6: only zimlore's own files -----------------------------------------------------------------------------


def test_prune_deletes_only_files_zimlore_installed_unless_told(home: Path) -> None:
    shared = build_zim(home / "zim", "s_2026-04.zim", date="2026-04-01")  # no sidecar: somebody else's library
    adopted = managed(build_zim(home / "zim", "s_2026-05.zim", date="2026-05-01"), "adopt")
    synced = managed(build_zim(home / "zim", "s_2026-06.zim", date="2026-06-01"), "sync")
    added = managed(build_zim(home / "zim", "s_2026-08.zim", date="2026-08-01"), "add")
    newest = build_zim(home / "zim", "s_2026-10.zim", date="2026-10-01")
    result = manage.prune(keep=1, apply=True)
    assert sorted(Path(d["file"]).name for d in result["deleted"]) == sorted([added.name, synced.name])
    assert sorted(Path(s["file"]).name for s in result["skipped"]) == sorted([adopted.name, shared.name])
    assert (
        shared.exists()
        and adopted.exists()
        and newest.exists()
        and "--include-unmanaged" in result["skipped"][0]["reason"]
    )
    everything = manage.prune(keep=1, apply=True, include_unmanaged=True)
    assert len(everything["deleted"]) == 2 and not shared.exists() and not adopted.exists()


# --- A8: adopt ------------------------------------------------------------------------------------------------


class _NoChecksum:
    has_checksum = False

    def __init__(self, archive: Any) -> None:
        self._archive = archive

    def __getattr__(self, name: str) -> Any:
        return getattr(self._archive, name)


def test_adopt_records_only_what_was_observed(home: Path) -> None:
    zim = build_zim(home / "zim")
    manage.verify(adopt=True)
    record, _ = manage.read_sidecar(zim)
    assert record is not None
    assert (record.source, record.catalogue_name, record.catalogue_date, record.fetched_at) == ("", "", "", "")
    assert record.added_by == "adopt" and record.adopted_at.endswith("Z")
    summary = manage.provenance_summary(zim)
    assert summary["fetched_at"] is None and summary["adopted_at"] == record.adopted_at


def test_adopt_takes_size_and_hash_from_the_file_not_from_the_scan(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zim = build_zim(home / "zim")
    real = manage._selected
    monkeypatch.setattr(manage, "_selected", lambda name: [dataclasses.replace(b, size=1) for b in real(name)])
    manage.verify(adopt=True)
    record, _ = manage.read_sidecar(zim)
    assert record is not None and record.size == zim.stat().st_size and record.sha256 == manage.sha256_of(zim)


def test_a_file_that_changes_length_while_it_is_hashed_is_an_error(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zim = build_zim(home / "zim")
    real = os.fstat
    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", lambda fd: SimpleNamespace(st_size=real(fd).st_size + 1))
        with pytest.raises(ZimloreError, match="changed while"):
            manage.hash_and_size(zim)
    digest, size = manage.hash_and_size(zim)
    assert (digest, size) == (manage.sha256_of(zim), zim.stat().st_size)


def test_adopting_a_zim_without_a_checksum_says_it_is_unchecked(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zim = build_zim(home / "zim")
    real = library.open_archive
    monkeypatch.setattr(library, "open_archive", lambda p: _NoChecksum(real(p)))
    row = manage.verify(adopt=True)["files"][0]
    assert row["status"] == "adopted-unchecked" and "no checksum" in row["note"] and row["libzim_checksum"] is None
    assert manage.sidecar_path(zim).exists()


# --- A9: the sidecar's own writes and deletes -------------------------------------------------------------


def test_the_sidecar_is_flushed_to_disk_before_it_replaces_the_old_one(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    zim = build_zim(home / "zim")
    events: list[str] = []
    real_fsync, real_replace = os.fsync, Path.replace

    def fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def replace(self: Path, target: Any) -> Path:
        events.append("replace")
        return real_replace(self, target)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)
    manage.write_sidecar(zim, manage.Provenance("u", "n", "d", "00" * 32, 1, "t", "get"))
    assert events == ["fsync", "replace"]


def test_a_failed_sidecar_write_leaves_no_temporary_file(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zim = build_zim(home / "zim")

    def refuse(self: Path, target: Any) -> Path:
        raise PermissionError(13, "denied")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(PermissionError):
        manage.write_sidecar(zim, manage.Provenance("u", "n", "d", "00" * 32, 1, "t", "get"))
    assert not list((home / "zim").glob("*.tmp"))


def test_stale_sidecar_temporary_files_are_swept_and_young_ones_left_alone(home: Path) -> None:
    folder = home / "zim"
    stale = folder / "a.zim.zimlore.json.tmp"
    stale.write_text("{")
    age(stale)
    young = folder / "b.zim.zimlore.json.tmp"
    young.write_text("{")
    assert manage.du()["stale_temp_files"] == 1
    assert _names(manage.prune()) == [stale.name]
    manage.prune(apply=True)
    assert not stale.exists() and young.exists()


def test_the_sidecar_goes_before_the_zim_and_comes_back_if_the_zim_cannot_go(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (zim,) = _editions(home, "2026-10-01")
    sidecar = manage.sidecar_path(zim)
    before = sidecar.read_text(encoding="utf-8")
    with monkeypatch.context() as patch:
        _lock_file(patch, zim.name)
        result = manage.remove("acme", apply=True)
    assert result["failed"] and zim.exists() and sidecar.read_text(encoding="utf-8") == before
    with monkeypatch.context() as patch:
        _lock_file(patch, sidecar.name)
        result = manage.remove("acme", apply=True)
    assert result["failed"] and zim.exists(), "a sidecar that cannot go stops the delete: no orphan can be left"
    result = manage.remove("acme", apply=True)
    assert result["ok"] and not zim.exists() and not sidecar.exists()


# --- the handle cache -----------------------------------------------------------------------------------------


def test_close_path_releases_one_file_and_leaves_the_other_cached(home: Path) -> None:
    first = build_zim(home / "zim", "x_a.zim", name="x_a", date="2026-01-01")
    second = build_zim(home / "zim", "x_b.zim", name="x_b", date="2026-01-01")
    library.read_book(first)
    library.read_book(second)
    library.close_path(first)
    first.unlink()  # a handle still open here would be WinError 32
    assert not any(k[0] == str(first) for k in library._ARCHIVES | library._BOOKS)
    assert any(k[0] == str(second) for k in library._ARCHIVES) and any(k[0] == str(second) for k in library._BOOKS)


def test_opening_a_replaced_file_drops_the_handle_to_the_old_one(home: Path) -> None:
    zim = build_zim(home / "zim")
    library.read_book(zim)
    stale = (str(zim), 1, 1)  # a handle opened before the file was replaced
    library._ARCHIVES[stale] = object()
    library._BOOKS[stale] = library.read_book(zim)
    library._ARCHIVES.pop(next(k for k in library._ARCHIVES if k != stale))  # force a fresh open
    library.open_archive(zim)
    assert stale not in library._ARCHIVES and stale not in library._BOOKS
    assert len([k for k in library._ARCHIVES if k[0] == str(zim)]) == 1


def test_remove_releases_only_the_handle_of_the_file_it_deletes(home: Path) -> None:
    old, new = _editions(home, "2026-08-01", "2026-10-01")
    manage.remove("acme", edition="2026-08-01", apply=True)
    assert not old.exists() and any(k[0] == str(new) for k in library._ARCHIVES)
