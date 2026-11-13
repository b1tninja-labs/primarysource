"""The Markdown, POD and scdoc readers over invented documents, hostile input included. No real text."""

from __future__ import annotations

import time

import pytest

from primarysource.errors import LibError
from primarysource.pkgdocs.readers.markdown import read_markdown
from primarysource.pkgdocs.readers.pod import MAX_CODED, read_pod, resolve_codes
from primarysource.pkgdocs.readers.scdoc import read_scdoc


def md(text: str) -> list[tuple[str, str, int, str]]:
    return [(s.id, s.title, s.depth, s.anchor) for s in read_markdown(text.encode(), "d").sections]


def test_atx_and_setext_levels_nest() -> None:
    text = "# One\n\na\n\nTwo\n---\n\nb\n\n## Three\n\nc\n\nFour\n====\n"
    assert [(i, t, d) for i, t, d, _ in md(text)] == [
        ("1", "One", 1),
        ("1.1", "Two", 2),
        ("1.2", "Three", 2),
        ("2", "Four", 1),
    ]


def test_a_fenced_block_with_hash_lines_is_not_a_heading_and_is_one_block() -> None:
    doc = read_markdown(b"# T\n\n```sh\n# comment, not a heading\necho hi\n```\n\nafter\n", "d")
    assert [s.title for s in doc.sections] == ["T"]
    assert doc.sections[0].units == ("```sh\n# comment, not a heading\necho hi\n```", "after")


def test_an_unclosed_fence_runs_to_the_end_without_losing_text() -> None:
    doc = read_markdown(b"# T\n\n```\nline one\n\nline two\n# still code\n", "d")
    assert doc.sections[0].units == ("```\nline one\n\nline two\n# still code",)


def test_duplicate_heading_slugs_are_suffixed() -> None:
    assert [a for *_, a in md("# Notes\n\n# Notes\n\n# Notes\n")] == ["notes", "notes-1", "notes-2"]


def test_front_matter_is_not_a_section_and_its_title_is_the_document_title() -> None:
    doc = read_markdown(b"---\nlayout: default\ntitle: Site - Tags\n---\n# Tags\n\ntext\n", "d")
    assert doc.title == "Site - Tags"
    assert [s.title for s in doc.sections] == ["Tags"]


def test_a_heading_that_skips_levels_leaves_no_gap_in_the_path() -> None:
    assert [(i, d) for i, _, d, _ in md("# A\n\n### B\n\n## C\n")] == [("1", 1), ("1.1", 2), ("1.2", 2)]


def test_text_before_the_first_heading_is_section_zero() -> None:
    doc = read_markdown(b"Preface words.\n\n# One\n\nx\n", "d", "Doc title")
    assert (doc.sections[0].id, doc.sections[0].title, doc.sections[0].units) == (
        "0",
        "Doc title",
        ("Preface words.",),
    )


def test_each_top_level_list_item_is_one_block_with_its_nested_items() -> None:
    text = "# T\n\n- one\n  - nested\n- two\n\n  second paragraph\n- three\n\n1. numbered\n"
    assert read_markdown(text.encode(), "d").sections[0].units == (
        "- one\n  - nested",
        "- two\n\n  second paragraph",
        "- three",
        "1. numbered",
    )


def test_tables_and_block_quotes_are_blocks_and_comments_hide_headings() -> None:
    text = "# T\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n> quoted\n> more\n\n<!--\n# hidden\n-->\n\nend\n"
    doc = read_markdown(text.encode(), "d")
    assert [s.title for s in doc.sections] == ["T"]
    assert doc.sections[0].units == ("| a | b |\n|---|---|\n| 1 | 2 |", "> quoted\n> more", "end")


def test_nothing_is_lost_between_blocks() -> None:
    text = "# T\n\nalpha\nbeta\n\n- gamma\n\n```\ndelta\n```\n\n    epsilon\n"
    units = "\n".join(read_markdown(text.encode(), "d").sections[0].units)
    for word in ("alpha\nbeta", "- gamma", "delta", "epsilon"):
        assert word in units


def test_a_1_mb_single_line_is_one_block_and_a_hostile_heading_is_linear() -> None:
    line = "w" * 1_000_000
    assert read_markdown(f"# T\n\n{line}\n".encode(), "d").sections[0].units == (line,)
    start = time.perf_counter()
    read_markdown(("# a" + " " * 200_000 + "x\n" + "#" * 100_000 + "\n").encode(), "d")
    assert time.perf_counter() - start < 3


@pytest.mark.parametrize("payload", [b"# T\n\n\x00\n", b"# T\n\n\xff\n"])
def test_nul_bytes_and_invalid_utf8_raise_liberror_with_a_hint(payload: bytes) -> None:
    with pytest.raises(LibError) as caught:
        read_markdown(payload, "d")
    assert caught.value.hint


POD = """# gadget manual page - frob(5)
#
# Copyright 2000 Nobody
#
# This is free software.

=encoding utf8

=head1 NAME

frob - Frob the B<gadget> I<now>

=head1 DESCRIPTION

Use C<< frob --all >> or C<frob> and E<lt>thisE<gt>; see L<other(1)>.

    verbatim line one
    verbatim line two

=head2 Options

=over

=item B<--all>

Everything.

Second paragraph of the item.

=item B<--none>

Nothing.

=back

=begin html

<p>hidden</p>

=end html

=head1 SEE ALSO

L<text|http://example.invalid/x>
"""


def test_pod_sections_items_and_codes_read_as_a_manual_page() -> None:
    doc = read_pod(POD.encode(), "frob")
    assert doc.title == "frob - Frob the gadget now"
    assert [(s.id, s.title) for s in doc.sections] == [
        ("1", "NAME"),
        ("2", "DESCRIPTION"),
        ("2.1", "Options"),
        ("3", "SEE ALSO"),
    ]
    description = doc.sections[1].units
    assert description[0] == "Use frob --all or frob and <this>; see other(1)."
    assert description[1].startswith("    verbatim line one")
    assert doc.sections[2].units == ("--all\n\nEverything.\n\nSecond paragraph of the item.", "--none\n\nNothing.")
    assert doc.sections[3].units == ("text",)
    assert "hidden" not in "".join("".join(s.units) for s in doc.sections)


def test_pod_codes_resolve_in_a_bounded_number_of_passes_and_unknown_letters_stay() -> None:
    assert resolve_codes("B<I<C<x>>>") == "x"
    assert resolve_codes("Q<keep>") == "Q<keep>"
    assert resolve_codes("E<0x41>E<65>E<verbar>") == "AA|"


def test_a_hostile_pod_paragraph_is_left_unresolved_and_reported() -> None:
    payload = "=head1 NAME\n\nx - y\n\n=head1 D\n\n" + "C<< " * (MAX_CODED // 2) + "\n"
    start = time.perf_counter()
    doc = read_pod(payload.encode(), "d")
    assert time.perf_counter() - start < 3
    assert doc.warnings and "left unresolved" in doc.warnings[0]


SCD = """RPM-THING(7)

; a comment
# NAME
*rpm-thing* - Do the thing

# DESCRIPTION
A paragraph
over two lines.

- bullet one
  continued
- bullet two

. numbered

```
literal text
```

## Details
More.
"""


def test_scdoc_reads_header_sections_lists_and_literals() -> None:
    doc = read_scdoc(SCD.encode(), "rpm-thing.7")
    assert doc.title == "rpm-thing(7)"
    assert [(s.id, s.title) for s in doc.sections] == [("1", "NAME"), ("2", "DESCRIPTION"), ("2.1", "Details")]
    assert doc.sections[1].units == (
        "A paragraph\nover two lines.",
        "- bullet one\n  continued",
        "- bullet two",
        ". numbered",
        "```\nliteral text\n```",
    )


def test_scdoc_refuses_nothing_but_binary_and_a_header_is_optional() -> None:
    assert read_scdoc(b"# A\ntext\n", "x").title == "x"
    with pytest.raises(LibError):
        read_scdoc(b"# A\n\x00\n", "x")
