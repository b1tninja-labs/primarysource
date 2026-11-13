"""The shared numbered-heading splitter (primarysource.pdfcorpus.split): the three fixes the NIST validation
measured (docs/validation.md), each on invented text. The usb and nist test suites cover the rest of it."""

from __future__ import annotations

from primarysource.pdfcorpus.split import split_sections


def _ids(text: str) -> list[str]:
    return [s.id for s in split_sections(text)]


def test_a_running_header_glued_before_a_heading_is_stripped() -> None:
    # pdftotext -layout puts the page header and the heading on one line (sp800-218 line 295)
    text = "\n".join(
        [
            "1 Introduction",
            "Invented.",
            "This publication is available free of charge from: https://doi.org/10.0000/INVENTED.1   2 Scope",
            "Invented.",
            "_________________________________________   3 Terms",
            "Invented.",
        ]
    )
    assert _ids(text) == ["1", "2", "3"]
    assert [s.heading for s in split_sections(text)][1] == "Scope"


def test_zero_padded_ids_count_as_children_of_their_unpadded_parent() -> None:
    # sp800-171r3 numbers its requirements 03.01.01 under section 3.1
    text = "\n".join(
        [
            "1 Introduction",
            "Invented.",
            "1.1 Purpose",
            "Invented.",
            "2 Scope",
            "Invented.",
            "2.1 Audience",
            "Invented.",
            "3 Requirements",
            "Invented.",
            "3.1 Access Control",
            "Invented.",
            "03.01.01 Account Management",
            "Invented.",
            "03.01.02 Access Enforcement",
            "Invented.",
        ]
    )
    # (chapters with no subsections and no contents listing are dropped as numbered steps, so 1 and 2 have one each)
    assert _ids(text) == ["1", "1.1", "2", "2.1", "3", "3.1", "03.01.01", "03.01.02"]


def test_appendix_headings_with_a_colon_or_dash() -> None:
    # "Appendix A: Title" (sp800-38c line 580) and the dash forms, besides "Appendix A. Title"
    text = "\n".join(
        [
            "1 Introduction",
            "Invented.",
            "Appendix A: Invented Tables",
            "Invented.",
            "Appendix B — Invented Figures",
            "Invented.",
            "APPENDIX C. Invented Notes",
            "Invented.",
        ]
    )
    assert _ids(text) == ["1", "A", "B", "C"]


def test_a_chapter_the_contents_lists_survives_a_stray_early_appendix_line() -> None:
    # The appendix rule (a bare number after an appendix is a list item) must not block a chapter the
    # contents lists: a front-matter "Appendix A. ..." line would otherwise drop every chapter (NIST sp800-204d).
    text = "\n".join(
        [
            "1 Introduction ............ 1",
            "2 Scope ................... 2",
            "",
            "Appendix A. Invented Cross-Reference In The Front Matter",
            "1 Introduction",
            "Invented.",
            "1.1 Purpose",
            "Invented.",
            "2 Scope",
            "Invented.",
            "2.1 Audience",
            "Invented.",
        ]
    )
    assert [s.id for s in split_sections(text)] == ["A", "1", "1.1", "2", "2.1"]


def test_a_long_tail_is_not_retracted_as_foreign() -> None:
    # A late "2.4" that is really a cross-reference must not retract the chapters accepted since 2.3
    # (more than _MAX_FOREIGN_TAIL of them): measured on NIST, unlimited retraction cost 0.05 median agreement.
    text = "\n".join(
        [
            "1 Introduction",
            "Invented.",
            "1.1 Purpose",
            "Invented.",
            "2 Design",
            "Invented.",
            "2.1 Parts",
            "Invented.",
            "2.2 Joins",
            "Invented.",
            "2.3 Finish",
            "Invented.",
            "3 Use",
            "Invented.",
            "3.1 Setup",
            "Invented.",
            "4 Care",
            "Invented.",
            "4.1 Cleaning",
            "Invented.",
            "2.4 As Described In The Design Chapter",
            "Invented.",
        ]
    )
    ids = [s.id for s in split_sections(text)]
    assert ids[:10] == ["1", "1.1", "2", "2.1", "2.2", "2.3", "3", "3.1", "4", "4.1"]
