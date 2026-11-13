"""Rules for the control-catalogue splitter, on small synthetic text (not NIST text)."""

from __future__ import annotations

from primarysource.nist.ingest.controls import split_control_sections


def ids(text: str) -> list[str]:
    return [s.id for s in split_control_sections(text)]


def test_control_and_its_enhancement_are_both_sections() -> None:
    text = "AC-2 ACCOUNT MANAGEMENT\nbody\n(1) ACCOUNT MANAGEMENT | AUTOMATED SYSTEM ACCOUNT MANAGEMENT\nbody\n"
    assert ids(text) == ["ac-2", "ac-2.1"]


def test_enhancement_number_is_taken_from_the_parent_not_the_page() -> None:
    text = "AC-2 ACCOUNT MANAGEMENT\n(1) FIRST\n(2) SECOND\n"
    assert ids(text) == ["ac-2", "ac-2.1", "ac-2.2"]


def test_prose_mention_in_capitals_is_not_a_heading() -> None:
    text = "AC-1 POLICY AND PROCEDURES\nSee the summary of AC-2 ACCOUNT MANAGEMENT for detail.\n"
    assert ids(text) == ["ac-1"]


def test_page_header_glued_to_a_control_heading_is_accepted() -> None:
    text = "This publication is available free of charge from: https://doi.org/10.6028/NIST.SP.800-53r5  AC-13 SUPERVISION AND REVIEW\n"
    assert ids(text) == ["ac-13"]


def test_first_occurrence_wins_over_the_summary_table() -> None:
    text = "AC-2 ACCOUNT MANAGEMENT\nbody\n\n    AC-2  ACCOUNT MANAGEMENT    O\n"
    sections = split_control_sections(text)
    assert [s.id for s in sections] == ["ac-2"]
    assert sections[0].heading == "ACCOUNT MANAGEMENT"


def test_section_runs_to_the_next_heading() -> None:
    text = "AC-1 POLICY AND PROCEDURES\na\nb\nAC-2 ACCOUNT MANAGEMENT\nc\n"
    first, second = split_control_sections(text)
    assert (first.start_line, first.end_line) == (1, 3)
    assert (second.start_line, second.end_line) == (4, 5)


def test_enhancement_glued_to_the_page_header_is_accepted() -> None:
    text = (
        "AC-6 LEAST PRIVILEGE\n(5) LEAST PRIVILEGE | PRIVILEGED ACCOUNTS\n"
        "This publication is available free of charge from: https://doi.org/10.6028/NIST.SP.800-53r5  "
        "(6) LEAST PRIVILEGE | PRIVILEGED ACCESS BY NON-ORGANIZATIONAL USERS\n"
    )
    assert ids(text) == ["ac-6", "ac-6.5", "ac-6.6"]


def test_enhancement_glued_to_the_page_header_needs_a_parent_and_capitals() -> None:
    header = "This publication is available free of charge from: https://doi.org/10.6028/NIST.SP.800-53r5  "
    assert ids(header + "(1) FIRST THING\n") == []
    assert ids("AC-6 LEAST PRIVILEGE\n" + header + "(1) see the text above\n") == [
        "ac-6"
    ]


def test_indexing_starts_at_the_first_dash_one_control() -> None:
    text = (
        "AU-4 AUDIT STORAGE CAPACITY\n(1) AUDIT STORAGE CAPACITY | TRANSFER\n"
        "AC-1 POLICY AND PROCEDURES\nAU-4 AUDIT LOG STORAGE CAPACITY\n"
    )
    sections = split_control_sections(text)
    assert [s.id for s in sections] == ["ac-1", "au-4"]
    assert sections[1].heading == "AUDIT LOG STORAGE CAPACITY"
