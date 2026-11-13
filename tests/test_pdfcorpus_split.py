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
