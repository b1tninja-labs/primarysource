from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from zimfixture import age, build_zim, managed

from primarysource.zim import library, manage, service
from primarysource.zim.errors import ZimloreError


def _two_editions(home: Path) -> tuple[Path, Path]:
    old = build_zim(home / "zim", "acme_en_widgets_2026-08.zim", date="2026-08-01")
    new = build_zim(home / "zim", "acme_en_widgets_2026-10.zim", date="2026-10-01")
    return old, new


def test_sidecar_round_trips_and_a_bad_one_is_reported_not_ignored(home: Path) -> None:
    zim = build_zim(home / "zim")
    assert manage.read_sidecar(zim) == (None, "")
    record = manage.Provenance("https://example.org/a.zim", "acme", "2026-10-01", "ab" * 32, 10, manage.now(), "get")
    manage.write_sidecar(zim, record)
    assert manage.read_sidecar(zim) == (record, "")
    manage.sidecar_path(zim).write_text("{broken", encoding="utf-8")
    loaded, problem = manage.read_sidecar(zim)
    assert loaded is None and problem, "a corrupt record is not the same as no record"
    manage.sidecar_path(zim).write_text(json.dumps({"schema": 99}), encoding="utf-8")
    assert "unknown schema 99" in manage.read_sidecar(zim)[1]


def test_provenance_is_shown_and_unknown_is_not_official(acme: Path) -> None:
    row = service.libraries()["libraries"][0]
    assert row["provenance"] == "unrecorded", "the lean row names the exception and nothing else"
    assert service.libraries(verbose=True)["libraries"][0]["provenance"]["state"] == "unrecorded"
    zim = library.scan().books[0].path
    manage.write_sidecar(zim, manage.Provenance("https://k.example/x.zim", "n", "d", "00" * 32, 1, "t", "get"))
    assert "provenance" not in service.libraries()["libraries"][0], "a recorded file costs no tokens in the lean row"
    assert service.libraries(verbose=True)["libraries"][0]["provenance"] == {
        "state": "recorded",
        "source": "https://k.example/x.zim",
        "sha256": "00" * 32,
        "fetched_at": "t",
        "added_by": "get",
    }
    assert service.cite("acme§guide/config")["provenance"]["added_by"] == "get"


def test_verify_ok_changed_corrupt_and_unrecorded(home: Path) -> None:
    zim = build_zim(home / "zim")
    unrecorded = manage.verify()["files"][0]
    assert unrecorded["status"] == "unrecorded" and unrecorded["libzim_checksum"] is True

    manage.write_sidecar(
        zim,
        manage.Provenance(
            "u", "acme_en_widgets", "2026-10-01", manage.sha256_of(zim), zim.stat().st_size, "t", "get"
        ),
    )
    assert manage.verify()["files"][0]["status"] == "ok"

    library.close_all()
    data = bytearray(zim.read_bytes())
    data[len(data) // 2] ^= 0xFF  # same length, different bytes
    zim.write_bytes(bytes(data))
    changed = manage.verify()
    assert changed["files"][0]["status"] == "changed" and "sha256" in changed["files"][0]["why"]
    assert changed["failed"] == 1
    size_only = manage.verify(hash_files=False)["files"][0]
    assert size_only["status"] == "corrupt", "without hashing, libzim's own checksum still catches the flipped byte"

    library.close_all()  # Windows keeps a ZIM locked while an Archive is open
    zim.write_bytes(bytes(data) + b"x")
    unopenable = manage.verify()
    assert unopenable["files"] == [] and unopenable["failed"] == 1, "a file libzim cannot open is a failure"
    assert unopenable["problems"][0]["path"].endswith(".zim")


def test_verify_adopt_records_what_a_file_is_without_claiming_where_it_came_from(home: Path) -> None:
    zim = build_zim(home / "zim")
    adopted = manage.verify(adopt=True)["files"][0]
    assert adopted["status"] == "adopted"
    record, _ = manage.read_sidecar(zim)
    assert record is not None and record.added_by == "adopt" and record.source == ""
    assert record.sha256 == manage.sha256_of(zim)
    assert manage.verify()["files"][0]["status"] == "ok"
    assert service.libraries(verbose=True)["libraries"][0]["provenance"]["source"] is None


def test_adopt_refuses_a_corrupt_file(home: Path) -> None:
    zim = build_zim(home / "zim")
    library.close_all()
    data = bytearray(zim.read_bytes())
    data[len(data) // 2] ^= 0xFF
    zim.write_bytes(bytes(data))
    row = manage.verify(adopt=True)["files"][0]
    assert row["status"] == "corrupt" and not manage.sidecar_path(zim).exists()


def test_remove_is_a_dry_run_unless_told_and_never_guesses_between_editions(home: Path) -> None:
    old, new = _two_editions(home)
    with pytest.raises(ZimloreError) as ambiguous:
        manage.remove("acme")
    assert ambiguous.value.extra["editions"] == ["2026-10-01", "2026-08-01"]
    assert "--edition" in ambiguous.value.hint
    dry = manage.remove("acme", edition="2026-08-01")
    assert dry["applied"] is False and dry["bytes"] == old.stat().st_size and old.exists()
    assert "dry run" in dry["note"]
    done = manage.remove("acme", edition="2026-08-01", apply=True)
    assert done["freed"] == dry["bytes"] and not old.exists() and new.exists()


def test_remove_deletes_the_sidecar_with_the_file_and_all_editions_on_request(home: Path) -> None:
    old, new = _two_editions(home)
    manage.write_sidecar(new, manage.Provenance("u", "n", "d", "00" * 32, 1, "t", "get"))
    result = manage.remove("acme", all_editions=True, apply=True)
    assert len(result["files"]) == 2 and not old.exists() and not new.exists()
    assert not manage.sidecar_path(new).exists()
    with pytest.raises(ZimloreError):
        manage.remove("acme")


def test_remove_unknown_edition_and_unknown_library(acme: Path) -> None:
    with pytest.raises(ZimloreError, match="no edition 1999-01-01"):
        manage.remove("acme", edition="1999-01-01")
    with pytest.raises(ZimloreError, match="no installed library"):
        manage.remove("cobol")


def test_prune_keeps_the_newest_editions_and_sweeps_partial_downloads(home: Path) -> None:
    managed(build_zim(home / "zim", "a_2026-06.zim", date="2026-06-01"))
    managed(build_zim(home / "zim", "a_2026-08.zim", date="2026-08-01"))
    newest = build_zim(home / "zim", "a_2026-10.zim", date="2026-10-01")
    other = build_zim(home / "zim", "b.zim", name="other_en_gadgets", title="Gadgets", date="2026-01-01")
    part = home / "zim" / "x_2026-10.zim.part"
    part.write_bytes(b"x" * 1000)
    age(part)
    dry = manage.prune(keep=2)
    assert {Path(i["file"]).name for i in dry["files"]} == {"a_2026-06.zim", "x_2026-10.zim.part"}
    assert (home / "zim" / "a_2026-06.zim").exists() and part.exists(), "a dry run deletes nothing"
    done = manage.prune(keep=2, apply=True)
    assert done["freed"] == dry["bytes"] and not part.exists()
    assert newest.exists() and other.exists() and (home / "zim" / "a_2026-08.zim").exists()
    assert not (home / "zim" / "a_2026-06.zim").exists()
    with pytest.raises(ZimloreError, match="at least 1"):
        manage.prune(keep=0)


def test_du_sums_editions_and_partial_downloads(home: Path) -> None:
    old, new = _two_editions(home)
    part = home / "zim" / "p.zim.part"
    part.write_bytes(b"y" * 500)
    age(part)
    usage = manage.du()
    row = usage["libraries"][0]
    assert (row["name"], row["editions"], row["newest"]) == ("acme_en_widgets", 2, "2026-10-01")
    assert row["bytes"] == old.stat().st_size + new.stat().st_size == usage["total_bytes"]
    assert usage["partial_bytes"] == 500 and usage["free_bytes"] and usage["free_bytes"] > 0


def test_manage_commands_on_an_empty_library_name_the_fix(home: Path) -> None:
    assert manage.du()["total_bytes"] == 0 and manage.du()["libraries"] == []
    calls: list[Callable[[], object]] = [manage.verify, lambda: manage.remove("x")]
    for call in calls:
        with pytest.raises(ZimloreError) as caught:
            call()
        assert "no ZIM files found" in caught.value.message
    assert manage.prune()["files"] == []


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    from primarysource.zim import cli

    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_remove_and_prune_are_dry_runs_until_yes(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old, new = _two_editions(home)
    managed(old)
    code, out, err = _run(capsys, "remove", "acme")
    assert code == 2 and "2 editions installed" in err
    code, out, _ = _run(capsys, "remove", "acme", "--edition", "2026-08-01")
    assert code == 0 and "would delete" in out and old.exists()
    code, out, _ = _run(capsys, "prune", "--keep", "1")
    assert code == 0 and "would delete" in out and old.exists()
    code, out, _ = _run(capsys, "prune", "--keep", "1", "--yes")
    assert "deleted" in out and not old.exists() and new.exists()


def test_cli_verify_exits_1_on_a_changed_file_and_du_prints_totals(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zim = build_zim(home / "zim")
    code, out, _ = _run(capsys, "verify", "--adopt")
    assert code == 0 and "adopted" in out
    code, out, _ = _run(capsys, "du")
    assert code == 0 and "acme_en_widgets" in out and "total in" in out
    library.close_all()
    data = bytearray(zim.read_bytes())
    data[len(data) // 2] ^= 0xFF
    zim.write_bytes(bytes(data))
    code, out, _ = _run(capsys, "verify")
    assert code == 1 and "changed" in out


def test_verify_reports_a_size_that_disagrees_with_the_record(home: Path) -> None:
    zim = build_zim(home / "zim")
    wrong = manage.Provenance("u", "n", "d", manage.sha256_of(zim), zim.stat().st_size + 1, "t", "get")
    manage.write_sidecar(zim, wrong)
    row = manage.verify(hash_files=False)["files"][0]
    assert row["status"] == "changed" and row["why"].startswith("size ")


# --- add ---------------------------------------------------------------------------------------------------


def _source(
    tmp_path: Path, filename: str = "widgets_2026-10.zim", *, date: str = "2026-10-01", license_text: str = ""
) -> Path:
    return build_zim(tmp_path / "elsewhere", filename, date=date, license_text=license_text)


def _flip(path: Path) -> None:
    library.close_all()
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))


def test_add_copies_a_local_zim_records_the_source_and_a_locally_computed_hash(home: Path, tmp_path: Path) -> None:
    source = _source(tmp_path, license_text="CC-BY-SA-4.0")
    result = manage.add_local(source)
    target = home / "zim" / source.name
    assert result["status"] == "added" and result["mode"] == "copy" and result["checksum"] is True
    assert target.read_bytes() == source.read_bytes() and source.exists(), "a copy; the original stays"
    record, problem = manage.read_sidecar(target)
    assert problem == "" and record is not None
    assert (record.added_by, record.source) == ("add", str(source.resolve()))
    assert (record.catalogue_name, record.catalogue_date) == ("acme_en_widgets", "2026-10-01")
    assert record.sha256 == manage.sha256_of(source) == result["sha256"] and record.size == source.stat().st_size
    assert [p.name for p in (home / "zim").glob("*.part")] == [], "no staging file is left"
    row = service.libraries(verbose=True)["libraries"][0]
    assert row["name"] == "acme_en_widgets" and row["provenance"]["added_by"] == "add"
    assert manage.verify()["files"][0]["status"] == "ok"


def test_add_refuses_a_file_libzim_cannot_open_and_copies_nothing(home: Path, tmp_path: Path) -> None:
    bad = tmp_path / "elsewhere" / "broken.zim"
    bad.parent.mkdir()
    bad.write_bytes(b"this is not a zim file at all" * 10)
    with pytest.raises(ZimloreError, match="not a readable ZIM") as caught:
        manage.add_local(bad)
    assert "nothing was copied" in caught.value.hint
    truncated = _source(tmp_path, "cut_2026-10.zim")
    truncated.write_bytes(truncated.read_bytes()[:300])
    with pytest.raises(ZimloreError, match="not a readable ZIM"):
        manage.add_local(truncated)
    assert list((home / "zim").iterdir()) == []
    with pytest.raises(ZimloreError, match="is not a file"):
        manage.add_local(tmp_path / "missing.zim")
    notzim = tmp_path / "elsewhere" / "notes.txt"
    notzim.write_text("x")
    with pytest.raises(ZimloreError, match="does not end in .zim"):
        manage.add_local(notzim)


def test_add_refuses_a_failed_checksum_unless_forced_and_says_so(home: Path, tmp_path: Path) -> None:
    source = _source(tmp_path)
    _flip(source)
    with pytest.raises(ZimloreError, match="fails libzim's own checksum") as caught:
        manage.add_local(source)
    assert "--force" in caught.value.hint and list((home / "zim").iterdir()) == []
    result = manage.add_local(source, force=True)
    assert result["forced"] is True and result["checksum"] is False
    assert manage.verify()["files"][0]["status"] == "corrupt", "verify keeps flagging a forced install"


def test_add_never_overwrites_a_different_file_and_is_idempotent_for_an_identical_one(
    home: Path, tmp_path: Path
) -> None:
    source = _source(tmp_path)
    manage.add_local(source)
    target = home / "zim" / source.name
    before = target.stat().st_mtime_ns
    again = manage.add_local(source)
    assert again["status"] == "already-installed" and target.stat().st_mtime_ns == before
    other = build_zim(tmp_path / "other", source.name, name="acme_en_gadgets", title="Gadgets", date="2026-01-01")
    with pytest.raises(ZimloreError, match="different file; not overwriting") as caught:
        manage.add_local(other)
    assert source.name in caught.value.message and target.read_bytes() == source.read_bytes()


def test_add_refuses_a_second_file_for_an_installed_edition_and_names_remove(home: Path, tmp_path: Path) -> None:
    manage.add_local(_source(tmp_path, "first_2026-10.zim"))
    twin = _source(tmp_path, "second_2026-10.zim")  # same Name and Date, another file
    with pytest.raises(ZimloreError, match="already installed as first_2026-10.zim") as caught:
        manage.add_local(twin)
    assert "primarysource zim remove acme_en_widgets --edition 2026-10-01 --yes" in caught.value.action
    assert [p.name for p in (home / "zim").glob("*.zim")] == ["first_2026-10.zim"]
    newer = _source(tmp_path, "third_2026-11.zim", date="2026-11-01")
    assert manage.add_local(newer)["status"] == "added", "another date is another edition and coexists"


def test_add_refuses_a_file_that_is_already_in_the_library_directory(home: Path) -> None:
    inside = build_zim(home / "zim")
    with pytest.raises(ZimloreError, match="already in the library directory") as caught:
        manage.add_local(inside)
    assert "verify --adopt" in caught.value.action


def test_add_link_makes_a_link_and_removing_the_edition_leaves_the_original(home: Path, tmp_path: Path) -> None:
    source = _source(tmp_path)
    result = manage.add_local(source, link=True)
    target = home / "zim" / source.name
    assert result["mode"] in {"hardlink", "symlink"} and target.read_bytes() == source.read_bytes()
    if result["mode"] == "hardlink":
        assert os.path.samefile(source, target)
    else:
        assert target.is_symlink() and target.resolve() == source.resolve()
    record, _ = manage.read_sidecar(target)
    assert record is not None and record.added_by == "add" and record.sha256 == manage.sha256_of(source)
    manage.remove("acme", apply=True)
    assert not target.exists() and source.is_file(), "removing a linked edition never deletes the original"


def test_add_link_that_the_os_refuses_is_a_clear_error_and_leaves_nothing(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: object, **__: object) -> None:
        raise OSError("operation not permitted")

    monkeypatch.setattr(os, "link", refuse)
    monkeypatch.setattr(os, "symlink", refuse)
    with pytest.raises(ZimloreError, match="refused both a hard link and a symbolic link") as caught:
        manage.add_local(_source(tmp_path), link=True)
    assert "omit --link" in caught.value.hint and list((home / "zim").iterdir()) == []


def test_cli_add_prints_the_licence_note_and_errors_exit_2(
    home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _source(tmp_path, license_text="CC-BY-SA-4.0")
    code, out, _ = _run(capsys, "add", str(source))
    assert code == 0 and "copied and recorded" in out and "licence: CC-BY-SA-4.0" in out
    code, out, _ = _run(capsys, "add", str(source))
    assert code == 0 and "already installed" in out
    code, out, err = _run(capsys, "add", str(tmp_path / "nothing.zim"))
    assert code == 2 and "is not a file" in err
    plain = _source(tmp_path, "plain_2026-11.zim", date="2026-11-01")
    code, out, _ = _run(capsys, "add", str(plain), "--link", "--json")
    assert code == 0 and json.loads(out)["mode"] in {"hardlink", "symlink"}
