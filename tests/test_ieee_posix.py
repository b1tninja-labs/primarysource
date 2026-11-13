"""The posix collection over invented pages shaped like The Open Group's HTML (see `ieee_posixfixture`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from ieee_posixfixture import CHAPTER, FROB, archive

from primarysource.errors import LibError
from primarysource.ieee import _html, posix
from primarysource.ieee.catalogue import Edition
from primarysource.ieee.importer import import_posix


@pytest.fixture
def installed(tmp_path: Path) -> tuple[Path, Edition]:
    path, pinned = archive(tmp_path)
    home = tmp_path / "home"
    import_posix(path, home=home, pinned=pinned)
    return home, pinned


def test_headings_take_their_anchor_from_the_empty_anchor_inside_them() -> None:
    converted = _html.convert(FROB, "functions/frob", _html.POSIX)
    assert [(h.level, h.text, h.anchor) for h in converted.headings] == [
        (4, "NAME", "tag_99_01_01"),
        (4, "DESCRIPTION", "tag_99_01_02"),
        (5, "Twiddling in Detail", "tag_99_01_02_01"),
        (4, "RETURN VALUE", "tag_99_01_03"),
    ]
    generic = _html.convert(FROB, "functions/frob")
    assert all(not h.anchor for h in generic.headings), "zimlore's rule alone loses every POSIX anchor"


def test_page_furniture_is_dropped_and_tables_inside_center_are_kept() -> None:
    text = _html.convert(FROB, "functions/frob", _html.POSIX).markdown
    for furniture in ("Previous", "Home", "Next", "Invented Banner", "trademark", "Main Index", "return to top"):
        assert furniture not in text, furniture
    assert "| F_ONE | one gasket |" in text
    assert "\n> " not in text and not text.startswith(">"), "a POSIX blockquote is indentation, not a quotation"


def test_the_page_ids_before_the_first_heading_still_find_it() -> None:
    loaded = posix.parse_page(FROB.encode(), "functions/frob")
    section = loaded.section_for("frob")
    assert section is not None and section.id == "tag_99_01_01"


def test_sections_hold_the_blocks_under_their_heading_with_subsections_included() -> None:
    loaded = posix.parse_page(FROB.encode(), "functions/frob")
    assert loaded.document.id == "posix-2024§functions/frob"
    description = loaded.document.section("tag_99_01_02")
    assert description is not None and description.depth == 4
    assert description.units[0] == "The *frob*() function shall twiddle the sprocket named by *s*."
    assert description.units[-1] == "Sub-section text about flanges."
    assert not any("RETURN VALUE" in unit for unit in description.units)
    assert not loaded.document.duplicate_ids()


def test_a_chapter_page_nests_numbered_headings() -> None:
    loaded = posix.parse_page(CHAPTER.encode(), "basedefs/V9_chap09")
    ids = [s.id for s in loaded.document.sections]
    assert ids == ["tag_98", "tag_98_01", "tag_98_02", "tag_98_03"]
    chapter = loaded.document.section("tag_98")
    assert chapter is not None and "Gasket term 3." in chapter.units


def test_read_a_section_a_block_and_a_whole_page(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    text = posix.read("posix-2024§functions/frob#tag_99_01_02¶2", home=home, edition=pinned)
    body, footer = text.split("\n\n", 1)
    assert body == "A second paragraph about gaskets."
    cite = "cite: IEEE Std 1003.1-2024 (The Open Group Base Specifications Issue 8), XSH frob, DESCRIPTION ¶2"
    assert cite in footer
    assert "unit: block" in footer and "span: sha256:" in footer
    whole = posix.read("functions/frob", home=home, edition=pinned)
    assert whole.startswith("#### NAME\n\nfrob - twiddle a sprocket")


def test_a_long_read_pages_and_says_where_to_continue(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    first = posix.read("posix-2024§functions/frob", max_tokens=3, home=home, edition=pinned)
    assert "next: start=2" in first
    rest = posix.read("posix-2024§functions/frob", start=2, max_tokens=10_000, home=home, edition=pinned)
    assert "next:" not in rest and "RETURN VALUE" in rest


def test_outline_lists_headings_with_their_refs(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    text = posix.outline("functions/frob", home=home, edition=pinned)
    assert "DESCRIPTION  posix-2024§functions/frob#tag_99_01_02\n" in text
    assert "  Twiddling in Detail  posix-2024§functions/frob#tag_99_01_02_01" in text


def test_grep_names_the_section_and_block_of_each_hit(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    text = posix.grep("GASKETS", home=home, edition=pinned)
    assert "posix-2024§functions/frob#tag_99_01_02¶2: A second paragraph about gaskets." in text
    assert posix.read("posix-2024§functions/frob#tag_99_01_02¶2", home=home, edition=pinned).startswith(
        "A second paragraph about gaskets."
    ), "a grep ref reads back the block it names"
    assert "no block contains" in posix.grep("quokka", home=home, edition=pinned)


def test_grep_is_bounded_and_resumable(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    text = posix.grep("gasket", limit=1, home=home, edition=pinned)
    assert text.count("posix-2024§") == 1 and "next: start=" in text
    with pytest.raises(LibError):
        posix.grep("x" * 201, home=home, edition=pinned)


def test_missing_pages_and_anchors_are_errors_that_suggest(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    with pytest.raises(LibError, match="no page") as caught:
        posix.read("posix-2024§functions/frab", home=home, edition=pinned)
    assert "functions/frob" in caught.value.hint
    with pytest.raises(LibError, match="no anchor") as caught:
        posix.read("posix-2024§functions/frob#tag_99_01_04", home=home, edition=pinned)
    assert "tag_99_01_0" in caught.value.hint
    with pytest.raises(LibError, match="not a POSIX page"):
        posix.load_page("../secret", home=home, edition=pinned)


def test_the_bracket_utility_has_a_page_id(installed: tuple[Path, Edition]) -> None:
    home, pinned = installed
    assert "utilities/[" in posix.pages("utilities", home=home, edition=pinned)
    assert "bracket test" in posix.read("posix-2024§utilities/[", home=home, edition=pinned)


def test_reading_before_import_names_the_download_and_the_import_command(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="not imported") as caught:
        posix.read("posix-2024§functions/open", home=tmp_path)
    assert "susv5.tgz" in caught.value.hint and "primarysource posix import" in caught.value.hint
