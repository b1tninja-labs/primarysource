"""Section splitter and pdftotext wrapper, on small synthetic text. No PDF is committed."""

from __future__ import annotations

import pytest

from primarysource.nist.ingest import extract
from primarysource.nist.ingest.extract import ExtractError, split_sections
from primarysource.nist.models import Section

SAMPLE = "\n".join(
    [
        "Contents",
        "1. Introduction.............................................1",
        "3.2.4. GENERAL AUTHENTICATE Card Command...................18",
        "",
        "1. Introduction",
        "Some prose.",
        "1.1. Purpose",
        "More prose.",
        "2. Overview",
        "1 A footnote that starts with a bare number.",
        "2.1. Platform Requirements",
        "2.2 No trailing dot heading",
        "3. Commands",
        "3.1. Reading",
        "3.2. Authentication",
        "3.2.1. VERIFY Card Command",
        "see 3.2.4. for the rest of the story.",
        "3.2.2. CHANGE REFERENCE DATA Card Command",
        "3.2.3. RESET RETRY COUNTER Card Command",
        "3.2.4. GENERAL AUTHENTICATE Card Command",
        "Body of the command.",
        "Appendix A. Examples",
        "A.1. First example",
        "A.1.1.1GENERAL AUTHENTICATE Command",
        "last line",
    ]
)


def by_id() -> dict[str, Section]:
    return {s.id: s for s in split_sections(SAMPLE)}


def test_finds_dotted_heading_with_text_and_line_range() -> None:
    section = by_id()["3.2.4"]
    assert section.heading == "GENERAL AUTHENTICATE Card Command"
    assert section.start_line == 20
    assert section.end_line == 21  # the line before "Appendix A."


def test_ids_in_document_order_and_nothing_extra() -> None:
    ids = [s.id for s in split_sections(SAMPLE)]
    assert ids == [
        "1",
        "1.1",
        "2",
        "2.1",
        "2.2",
        "3",
        "3.1",
        "3.2",
        "3.2.1",
        "3.2.2",
        "3.2.3",
        "3.2.4",
        "A",
        "A.1",
    ]


def test_table_of_contents_rows_are_not_headings() -> None:
    # The TOC row for 3.2.4 comes first in the text; the real heading must win.
    assert by_id()["3.2.4"].start_line != 3
    assert by_id()["1"].start_line == 5


def test_footnote_and_cross_reference_are_not_headings() -> None:
    sections = by_id()
    assert (
        sections["2"].end_line == 10
    )  # the "1 A footnote" line stays inside section 2
    assert (
        sections["3.2.1"].end_line == 17
    )  # "see 3.2.4. for ..." did not start a section


def test_last_section_runs_to_end_and_sections_partition_the_text() -> None:
    sections = split_sections(SAMPLE)
    lines = SAMPLE.count("\n") + 1
    assert sections[-1].end_line == lines
    for current, following in zip(sections, sections[1:], strict=False):
        assert following.start_line == current.end_line + 1


def test_form_feed_does_not_shift_line_numbers() -> None:
    text = "1. One\nbody\n\f2. Two\nbody\n"
    sections = split_sections(text)
    assert [(s.id, s.start_line, s.end_line) for s in sections] == [
        ("1", 1, 2),
        ("2", 3, 4),
    ]


def test_appendix_and_glued_heading() -> None:
    sections = by_id()
    assert sections["A"].heading == "Examples"
    assert "A.1.1.1" not in sections  # parent A.1.1 never seen, so no orphan section


def test_numbered_list_items_after_the_chapters_are_ignored() -> None:
    chapters = "".join(f"{n}. Chapter {n}\nbody\n" for n in range(1, 6))
    text = chapters + "1. First item\n2. Second item\n3. Third item\n"
    assert [s.id for s in split_sections(text)] == ["1", "2", "3", "4", "5"]


def test_empty_text_has_no_sections() -> None:
    assert split_sections("") == ()


def test_missing_pdftotext_has_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extract.shutil, "which", lambda _name: None)
    with pytest.raises(ExtractError, match="pdftotext was not found on PATH"):
        extract.find_pdftotext()


def test_dotless_chapter_heading_is_accepted() -> None:
    """USB-IF CCID writes chapters as "3 CCID Functional Characteristics", with no trailing dot."""
    text = "\n".join(
        ["1 Introduction", "body", "2 Overview", "body", "3 CCID Functional Characteristics", "body"]
    )
    ids = [s.id for s in split_sections(text)]
    assert ids == ["1", "2", "3"]


def test_dotless_table_row_with_column_gaps_is_not_a_heading() -> None:
    """A table row such as "3 Fh to 01h     Command not supported" must not open chapter 3, even though 3 is the next number."""
    text = "\n".join(
        [
            "1 Introduction",
            "body",
            "2 Overview",
            "body",
            "3 Fh to 01h     Command not supported",
            "body",
        ]
    )
    ids = [s.id for s in split_sections(text)]
    assert ids == ["1", "2"]
