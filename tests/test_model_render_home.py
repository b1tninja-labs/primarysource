from __future__ import annotations

from pathlib import Path

import pytest

from primarysource.budget import page
from primarysource.errors import LibError
from primarysource.home import atomic_write, resolve_home
from primarysource.model import Document, Section, Unit, span_hash
from primarysource.render import next_start, parse_next_start, render


def _document() -> Document:
    sections = (
        Section("1", "Scope", ("First.", "Second.")),
        Section("2", "Terms", ("Only.",)),
        Section("2", "Terms again", ("Other.",)),
    )
    return Document("doc", "A document", Unit.SENTENCE, sections)


def test_a_section_is_found_by_id_and_a_missing_one_is_none() -> None:
    document = _document()
    found = document.section("1")
    assert found is not None and found.units == ("First.", "Second.")
    assert document.section("9") is None


def test_duplicate_section_ids_are_reported_and_the_first_wins() -> None:
    document = _document()
    assert document.duplicate_ids() == ("2",)
    found = document.section("2")
    assert found is not None and found.title == "Terms"


def test_span_hash_is_stable_and_changes_with_the_text() -> None:
    assert span_hash("abc") == "sha256:ba7816bf8f01cfea"
    assert span_hash("abc") != span_hash("abd")


def test_footer_lines_come_out_in_the_fixed_order_and_empty_ones_are_dropped() -> None:
    text = render("Body line.\n", {"next": "doc§1¶3", "cite": "Doc §1", "warning": "", "unit": "sentence"})
    assert text == "Body line.\n\ncite: Doc §1\nunit: sentence\nnext: doc§1¶3\n"


def test_a_result_with_no_footer_is_just_the_body() -> None:
    assert render("Body.", {}) == "Body.\n"


def test_an_unknown_footer_key_or_a_multiline_value_is_a_bug() -> None:
    with pytest.raises(ValueError):
        render("Body.", {"citation": "x"})
    with pytest.raises(ValueError):
        render("Body.", {"cite": "one\ntwo"})


def test_a_list_footer_says_next_start_and_the_value_is_what_to_pass_back() -> None:
    # a list page continuing at 0-based offset 40: the footer line, and parsing it, give back exactly 40
    text = render("hit 1\nhit 2", {"next": next_start(40)})
    assert text.endswith("\nnext: start=40\n")
    value = text.rstrip("\n").rsplit("\n", 1)[1].removeprefix("next: ")
    assert parse_next_start(value) == 40
    assert next_start(0) == "start=0"
    # the last page has no cursor, and render then prints no next: line at all
    assert next_start(None) == ""
    assert "next:" not in render("last hit", {"next": next_start(None)})


def test_a_list_cursor_follows_a_pager_to_the_end_without_loss() -> None:
    units = [f"hit {n}" * 30 for n in range(12)]
    seen: list[str] = []
    cursor: str = next_start(0)
    while cursor:
        offset = parse_next_start(cursor)
        got = page(units, start=offset + 1, max_tokens=200)  # the pager is 1-based; the cursor is 0-based
        seen.extend(got.units)
        cursor = next_start(None if got.next_start is None else got.next_start - 1)
    assert seen == units


@pytest.mark.parametrize("value", ["40", "start=-1", "start=01", "start=", "next=4", "start=4 more"])
def test_a_malformed_list_cursor_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="not a list cursor"):
        parse_next_start(value)
    with pytest.raises(ValueError):
        next_start(-1)


def test_an_error_carries_its_hint_into_the_text() -> None:
    assert LibError("no index", "run: x index").as_text() == "error: no index\nhint: run: x index"
    assert LibError("no index").as_text() == "error: no index"


def test_home_prefers_the_variable_then_the_per_user_directory() -> None:
    assert resolve_home("nistlib", {"NISTLIB_HOME": "/data"}, "linux") == Path("/data")
    assert resolve_home("nistlib", {"LOCALAPPDATA": "C:/L"}, "win32") == Path("C:/L") / "nistlib"
    assert resolve_home("nistlib", {"XDG_DATA_HOME": "/x"}, "linux") == Path("/x") / "nistlib"
    assert resolve_home("nistlib", {}, "linux") == Path.home() / ".local" / "share" / "nistlib"
    assert resolve_home("nistlib", {}, "darwin") == Path.home() / "Library" / "Application Support" / "nistlib"


def test_atomic_write_replaces_the_file_and_leaves_no_part_file(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "index.json"
    atomic_write(target, b"one")
    atomic_write(target, b"two")
    assert target.read_bytes() == b"two"
    assert [entry.name for entry in target.parent.iterdir()] == ["index.json"]


def test_collection_home_keeps_old_settings_and_libraries(tmp_path: Path) -> None:
    from primarysource.home import collection_home

    base = {"LOCALAPPDATA": str(tmp_path), "XDG_DATA_HOME": str(tmp_path)}
    plat = "linux"
    assert collection_home("rfc", "rfclib", {**base, "RFCLIB_HOME": "/x", "PRIMARYSOURCE_HOME": "/y"}, plat) == Path(
        "/x"
    )
    assert collection_home("rfc", "rfclib", {**base, "PRIMARYSOURCE_HOME": "/y"}, plat) == Path("/y") / "rfc"
    assert collection_home("rfc", "rfclib", base, plat) == tmp_path / "primarysource" / "rfc"
    (tmp_path / "rfclib").mkdir()
    assert collection_home("rfc", "rfclib", base, plat) == tmp_path / "rfclib"
    assert collection_home("nist", None, base, plat) == tmp_path / "primarysource" / "nist"
