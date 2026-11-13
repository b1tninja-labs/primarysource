"""Section splitter and pdftotext wrapper, on small synthetic text. No PDF is committed."""

from __future__ import annotations

import pytest

from primarysource.usb.ingest import extract
from primarysource.usb.ingest.extract import ExtractError, split_sections
from primarysource.usb.models import Section

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
        [
            "1 Introduction",
            "body",
            "2 Overview",
            "body",
            "3 CCID Functional Characteristics",
            "body",
        ]
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


def _chapters(*numbers: int) -> str:
    return "".join(f"{n}.1 Part\nbody\n" for n in numbers)


def test_page_footer_after_a_page_number_is_not_the_next_chapter() -> None:
    # "5     Revision 1.0" closes every page; the page number must not pass as chapter 5.
    text = "\n".join(
        [
            "1 Introduction",
            "1.1 Scope",
            "4 pages of text",
            "2 Revision 1.0",
            "3 Revision 1.0",
            "2 Descriptors",
            "2.1 Interface",
            "4 Revision 1.0",
            "3 Operation",
            "3.1 Model",
        ]
    )
    assert [s.id for s in split_sections(text)] == [
        "1",
        "1.1",
        "2",
        "2.1",
        "3",
        "3.1",
    ]


def test_list_item_read_as_next_chapter_is_retracted_by_a_later_subsection() -> None:
    text = "\n".join(
        [
            "1 Introduction",
            "1.1 Scope",
            "2 Tests",
            "2.1 Setup",
            "2.2 Procedure",
            "3 Verify that the link is up",
            "2.3 Cleanup",
            "3 Results",
            "3.1 Table",
        ]
    )
    sections = split_sections(text)
    assert [s.id for s in sections] == [
        "1",
        "1.1",
        "2",
        "2.1",
        "2.2",
        "2.3",
        "3",
        "3.1",
    ]
    assert sections[-2].heading == "Results"


def test_runs_of_numbered_steps_without_subsections_are_not_chapters() -> None:
    text = "\n".join(
        [
            "1 Introduction",
            "1.1 Scope",
            "2 Procedure",
            "2.1 Setup",
            "3 Plug the device into the port",
            "4 Check the scope for a waveform",
            "5 Save the capture",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["1", "1.1", "2", "2.1"]


def test_lone_chapter_without_subsections_is_kept() -> None:
    text = "1 Introduction\n1.1 Scope\n2 Normative References\n3 Operation\n3.1 Model\n"
    assert [s.id for s in split_sections(text)] == ["1", "1.1", "2", "3", "3.1"]


def test_childless_chapters_listed_in_the_contents_are_kept() -> None:
    text = "\n".join(
        [
            "1 Introduction ............ 1",
            "2 Management Overview ..... 3",
            "3 Functional Characteristics ... 5",
            "1 Introduction",
            "1.1 Scope",
            "2 Management Overview",
            "3 Functional Characteristics",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["1", "1.1", "2", "3"]


def test_chapter_heading_on_one_line_is_a_chapter() -> None:
    # Power Delivery writes "Chapter N. Title" on a single line.
    text = "\n".join(
        ["Chapter 1. Introduction", "1.1 Scope", "body", "Chapter 2. Glossary", "2.1 Terms", "body"]
    )
    sections = {s.id: s for s in split_sections(text)}
    assert list(sections) == ["1", "1.1", "2", "2.1"]
    assert sections["1"].heading == "Introduction"
    assert sections["2"].heading == "Glossary"


def test_chapter_number_with_title_on_the_next_line_is_a_chapter() -> None:
    # USB 2.0 puts "Chapter N" on one line and the title centred on the line after it.
    text = "\n".join(
        ["Chapter 1", "Introduction", "1.1 Motivation", "body", "Chapter 2", "Terms", "2.1 Use", "body"]
    )
    sections = {s.id: s for s in split_sections(text)}
    assert list(sections) == ["1", "1.1", "2", "2.1"]
    assert sections["1"].heading == "Introduction"
    assert sections["2"].heading == "Terms"


def test_chapter_header_repeated_on_every_page_does_not_drop_its_chapter() -> None:
    # "Chapter 1. Introduction" closes or opens every page of chapter 1: a running header, not a footer.
    text = "\n".join(
        ["Chapter 1. Introduction", "1.1 Scope", "body"] * 4
        + ["Chapter 2. Glossary", "2.1 Terms", "body"] * 3
    )
    assert [s.id for s in split_sections(text)] == ["1", "1.1", "2", "2.1"]


def test_prose_that_starts_with_chapter_number_is_not_a_heading() -> None:
    text = "\n".join(
        ["Chapter 1. Introduction", "1.1 Scope", "Chapter 2 describes the bus:", "body", "Chapter 2. Glossary", "2.1 Terms"]
    )
    sections = {s.id: s for s in split_sections(text)}
    assert list(sections) == ["1", "1.1", "2", "2.1"]
    assert sections["2"].heading == "Glossary"


def test_numbered_list_item_before_the_real_chapter_is_not_the_chapter() -> None:
    # Power Delivery: a list item "4. A Source May ..." sits in chapter 3, ahead of the real "Chapter 4.".
    text = "\n".join(
        [
            "Chapter 1. Introduction",
            "1.1 Scope",
            "Chapter 2. Glossary",
            "2.1 Terms",
            "Chapter 3. Port Power Requirements",
            "3.1 Scope",
            "body",
            "4. A Source May offer a Variable PDO, a Battery PDO, or a higher Maximum Current:",
            "body",
            "Chapter 4. Power Delivery Electrical Requirements",
            "4.1 Source Requirements",
            "body",
        ]
    )
    sections = {s.id: s for s in split_sections(text)}
    assert sections["4"].heading == "Power Delivery Electrical Requirements"
    assert sections["4"].start_line == 10


def test_childless_chapters_listed_in_a_space_leader_contents_are_kept() -> None:
    # HID Usage Tables lists "1 Introduction      15" with spaces, not a dot leader. Chapters 1 and 2 have
    # no subsections and sit side by side, so only the contents listing keeps them from being read as steps.
    text = "\n".join(
        [
            "1 Introduction                    15",
            "2 Management Overview             16",
            "3 Usage Pages                     17",
            "3.1 Conventions",
            "body",
            "1 Introduction",
            "body",
            "2 Management Overview",
            "body",
            "3 Usage Pages",
            "3.1 Conventions",
            "body",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["1", "2", "3", "3.1"]


def test_margin_line_number_before_a_dotted_heading_is_stripped() -> None:
    # Inter-Chip Supplement prints a margin line number before every line: "119  2.2.3 M-TX Capabilities".
    text = "\n".join(
        [
            "1 Introduction",
            "2 M-PHY MODULE",
            "117  2.1 Basics",
            "118  2.2 M-PHY MODULE Capabilities",
            "119  2.2.1 Profile Definitions",
            "120  An implementation shall ensure that the local ports are configured.",
            "121  2.2.2 Multi-LANE Capabilities",
            "122  32  SSIC has been designed to replace a standard controller.",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["1", "2", "2.1", "2.2", "2.2.1", "2.2.2"]


_SHALLOW_CONTENTS = [
    "Contents",
    "1 Introduction ........................ 5",
    "3 Overview ............................ 7",
    "4 Tests ............................... 9",
    "4.1 Scope .............................. 9",
]


def test_running_text_under_a_chapter_the_contents_shows_without_subsections_is_not_a_section() -> None:
    # The contents lists 4.1 but no subsection of chapter 3, so "3.1 ...: two pairs" is a cross-reference.
    text = "\n".join(
        _SHALLOW_CONTENTS
        + [
            "1 Introduction",
            "1.1 Purpose",
            "body",
            "2 Background",
            "2.1 Scope",
            "body",
            "3 Overview",
            "body",
            "3.1 Connector includes five pins: two differential signal pairs plus power",
            "body",
            "4 Tests",
            "4.1 Scope",
            "body",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["1", "1.1", "2", "2.1", "3", "4", "4.1"]


def test_label_ending_in_a_colon_under_a_shallow_chapter_is_kept() -> None:
    # "Registry Hive Root:" is a subsection label; it is a heading, not running text.
    text = "\n".join(
        _SHALLOW_CONTENTS
        + [
            "1 Introduction",
            "1.1 Purpose",
            "body",
            "2 Background",
            "body",
            "3 Overview",
            "body",
            "4 Tests",
            "4.1 Registry Hive Root:",
            "body",
        ]
    )
    assert "4.1" in [s.id for s in split_sections(text)]


def test_a_missed_heading_does_not_drop_its_later_siblings_listed_in_the_contents() -> None:
    # 2.2's title starts lowercase, so it is not read as a heading. Before the fix, 2.3 was then never "next"
    # and was dropped with everything after it (docs/validation.md, usb: 1,485 of 1,749 misses). The contents
    # lists 2.3 and 2.4, so they are admitted, and the sequence resumes after them.
    text = "\n".join(
        [
            "Contents",
            "1 Scope ................................ 1",
            "2 Widgets .............................. 2",
            "2.1 Round Widgets ...................... 2",
            "2.2 square widgets ..................... 3",
            "2.3 Oval Widgets ....................... 4",
            "2.4 Flat Widgets ....................... 5",
            "",
            "1 Scope",
            "Invented text for a test.",
            "2 Widgets",
            "Widgets are invented.",
            "2.1 Round Widgets",
            "Round.",
            "2.2 square widgets",
            "Square.",
            "2.3 Oval Widgets",
            "Oval.",
            "2.4 Flat Widgets",
            "Flat.",
            "2.4.1 Thin Flat Widgets",
            "Thin.",
        ]
    )
    ids = [s.id for s in split_sections(text)]
    assert ids == ["1", "2", "2.1", "2.3", "2.4", "2.4.1"]


def test_a_number_not_in_the_contents_still_needs_to_be_next() -> None:
    # The contents admits only what it lists; an unlisted jump is still a list item or a cross-reference.
    text = "\n".join(
        [
            "1 Scope ................................ 1",
            "2 Widgets .............................. 2",
            "",
            "1 Scope",
            "Invented.",
            "2 Widgets",
            "Invented.",
            "2.5 Settings Described Elsewhere",
            "Invented.",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["1", "2"]
