"""Prose-document layouts, on small synthetic text. Each fixture mirrors what pdftotext produced for a real family."""

from __future__ import annotations

import pytest

from primarysource.nist.ingest.prose_layouts import LAYOUTS, detect_layout, split_for_layout

HDR = "This publication is available free of charge from: https://doi.org/10.6028/NIST.SP.800-999  "
PAD = " " * 90


def ids(text: str, layout: str) -> list[str]:
    return [s.id for s in split_for_layout(text, layout)]


NUMBERED = "\n".join(
    [
        "Table of Contents",
        PAD + "1 Introduction .................................... 1",
        PAD + "1.1 Purpose ........................................ 1",
        "",
        HDR + "1 Introduction",
        "",
        PAD + "1.1 Purpose and Scope",
        PAD + "prose",
        PAD + "1.2 Audience",
        HDR + "2 Elements of Email",
        PAD + "2 Although MUAs often use port 587 when submitting email.",
        PAD + "2.1 Components",
        PAD + "3 Administrators should consult their documentation",
        HDR + "3 Security Threats",
        PAD + "3.1 Threats",
        PAD + "3.1.1 Spoofing",
        PAD + "see 3.1.2 Phishing for more",
        PAD + "3.1.2 Phishing",
        PAD + "3.3 Skipped sibling",
        HDR + "Appendix A—Acronyms",
        HDR + "Appendix B Revision History",
        PAD + "Appendix C provides the user with a template",
        "Appendix C: References",
    ]
)


def test_numbered_reads_chapters_glued_behind_the_running_header() -> None:
    # The generic splitter sees no "1" here: the heading shares a line with the page header.
    got = split_for_layout(NUMBERED, "numbered")
    assert [s.id for s in got] == [
        "1",
        "1.1",
        "1.2",
        "2",
        "2.1",
        "3",
        "3.1",
        "3.1.1",
        "3.1.2",
        "A",
        "B",
        "C",
    ]
    assert got[0].heading == "Introduction"
    assert got[0].start_line == 5


def test_numbered_footnote_does_not_take_the_chapter_place() -> None:
    # "3 Administrators ..." precedes the real glued chapter 3 and must not become it.
    got = {s.id: s for s in split_for_layout(NUMBERED, "numbered")}
    assert got["3"].heading == "Security Threats"
    assert (
        got["2"].heading == "Elements of Email"
    )  # the footnote "2 Although ..." ends in a full stop


def test_numbered_ignores_contents_rows_and_out_of_order_ids() -> None:
    got = ids(NUMBERED, "numbered")
    assert got.count("1.1") == 1  # the contents row has leader dots
    assert "3.3" not in got  # 3.2 never appeared


def test_numbered_appendix_forms() -> None:
    got = {
        s.id: s.heading for s in split_for_layout(NUMBERED, "numbered") if s.id in "ABC"
    }
    # "Appendix B Revision History" counts because it opens a page; the prose "Appendix C provides" does not.
    assert got == {"A": "Acronyms", "B": "Revision History", "C": "References"}


ZERO = "\n".join(
    [
        "Contents",
        "1.0 Introduction ............................ 1",
        "1.0 Introduction",
        "prose",
        "2.0 Basis for Identification",
        "3.0 Method",
        "3.1 Determination of Responsibilities",
        "3.2 Checklist",
        "1 * See Glossary definition for classified information.",
        "Appendix A: Checklist",
        "A.1 Minimum Question Set",
        "A.1.1 Intelligence Activities",
    ]
)


def test_numbered_zero_collapses_n_dot_zero_to_the_chapter_id() -> None:
    got = split_for_layout(ZERO, "numbered_zero")
    assert [s.id for s in got] == ["1", "2", "3", "3.1", "3.2", "A", "A.1", "A.1.1"]
    assert got[0].start_line == 3  # not the contents row on line 2


SECTION = "\n".join(
    [
        "SECTION 1: INTRODUCTION ........................ 1",
        PAD + "SECTION 1: INTRODUCTION",
        HDR + "1.1 Background and Purpose",
        "Section 302 of the Act directs the Secretary",
        HDR + "SECTION 2: APPLICABLE PUBLIC LAWS",
        PAD + "2.1 Federal Information Security Act",
        HDR + "SECTION 3: EXECUTIVE DIRECTION",
        HDR + "APPENDIX A: REFERENCES",
    ]
)


def test_section_colon_chapters() -> None:
    got = split_for_layout(SECTION, "section_colon")
    assert [(s.id, s.heading) for s in got] == [
        ("1", "INTRODUCTION"),
        ("1.1", "Background and Purpose"),
        ("2", "APPLICABLE PUBLIC LAWS"),
        ("2.1", "Federal Information Security Act"),
        ("3", "EXECUTIVE DIRECTION"),
        ("A", "REFERENCES"),
    ]


WORD = "\n".join(
    [
        PAD + "CHAPTER ONE INTRODUCTION ..................... 1",
        HDR + "CHAPTER ONE",
        "",
        PAD + "INTRODUCTION",
        PAD + "1.1 PURPOSE AND APPLICABILITY",
        PAD + "CHAPTER ONE      PAGE 2",
        PAD + "1.2 TARGET AUDIENCE",
        PAD + "CHAPTER TWO",
        "",
        PAD + "THE FUNDAMENTALS",
        PAD + "2.1 CONTROL BASELINES",
        PAD + "CHAPTER TWO      PAGE 6",
        PAD + "CHAPTER THREE",
        PAD + "THE CONTROL BASELINES",
        PAD + "APPENDIX A",
        "",
        PAD + "GLOSSARY",
        PAD + "APPENDIX A      PAGE 59",
    ]
)


def test_chapter_word_takes_the_title_from_the_next_line() -> None:
    got = split_for_layout(WORD, "chapter_word")
    assert [(s.id, s.heading) for s in got] == [
        ("1", "INTRODUCTION"),
        ("1.1", "PURPOSE AND APPLICABILITY"),
        ("1.2", "TARGET AUDIENCE"),
        ("2", "THE FUNDAMENTALS"),
        ("2.1", "CONTROL BASELINES"),
        ("3", "THE CONTROL BASELINES"),
        ("A", "GLOSSARY"),
    ]
    assert got[0].start_line == 2  # the CHAPTER line, not the contents row


def test_sections_tile_the_text_without_gaps() -> None:
    for text, layout in (
        (NUMBERED, "numbered"),
        (WORD, "chapter_word"),
        (SECTION, "section_colon"),
    ):
        got = split_for_layout(text, layout)
        for before, after in zip(got, got[1:], strict=False):
            assert after.start_line == before.end_line + 1
        assert got[-1].end_line == len(text.split("\n"))


@pytest.mark.parametrize(
    ("text", "layout"),
    [
        (NUMBERED, "numbered"),
        (ZERO, "numbered_zero"),
        (SECTION, "section_colon"),
        (WORD, "chapter_word"),
    ],
)
def test_detect_layout_picks_the_matching_style(text: str, layout: str) -> None:
    assert detect_layout(text) == layout


def test_detect_layout_is_none_without_numbered_headings() -> None:
    prose = "\n".join(
        ["FOREWORD", "Some words about the year.", "CRYPTOGRAPHY", "More words."] * 10
    )
    assert detect_layout(prose) is None


def test_each_layout_finds_nothing_in_text_written_in_another() -> None:
    def numeric(text: str, layout: str) -> list[str]:
        return [
            i for i in ids(text, layout) if i[0].isdigit()
        ]  # appendices are shared by every layout

    assert numeric(WORD, "numbered") == []
    assert numeric(NUMBERED, "chapter_word") == []
    assert numeric(ZERO, "section_colon") == []


def test_unknown_layout_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown layout"):
        split_for_layout("1 Introduction", "roman")
    assert "numbered" in LAYOUTS
