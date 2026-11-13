"""The AsciiDoc reader over invented documents, hostile input included. No real text."""

from __future__ import annotations

import time

import pytest

from primarysource.errors import LibError
from primarysource.pkgdocs.readers.asciidoc import read_asciidoc


def read(text: str, doc_id: str = "gadget-frob(7)") -> tuple[tuple[str, str, int], ...]:
    doc = read_asciidoc(text.encode(), doc_id)
    return tuple((s.id, s.title, s.depth) for s in doc.sections)


MANPAGE = """gadget-frob(7)
==============

NAME
----
gadget-frob - Frob the gadget

DESCRIPTION
-----------

Frobbing is done by turning the knob.

== Knob positions

The knob has three positions.

=== Position one

Fully left.

== Last words

Done.
"""


def test_the_underlined_title_is_the_document_title_and_underlines_and_equals_signs_nest() -> None:
    doc = read_asciidoc(MANPAGE.encode(), "gadget-frob")
    assert doc.title == "gadget-frob(7)"
    assert [(s.id, s.title, s.depth) for s in doc.sections] == [
        ("1", "NAME", 1),
        ("2", "DESCRIPTION", 1),
        ("3", "Knob positions", 1),
        ("3.1", "Position one", 2),
        ("4", "Last words", 1),
    ]
    assert doc.section("1") is not None and doc.section("1").units == ("gadget-frob - Frob the gadget",)  # type: ignore[union-attr]


def test_an_atx_title_and_a_skipped_level_keep_a_gapless_path() -> None:
    doc = read_asciidoc(b"= Whole thing\n\n== One\n\ntext\n\n==== Deep\n\nmore\n\n== Two\n", "d")
    assert doc.title == "Whole thing"
    assert [(s.id, s.depth) for s in doc.sections] == [("1", 1), ("1.1", 2), ("2", 1)]


def test_an_explicit_anchor_before_a_heading_is_its_anchor_and_a_slug_is_the_default() -> None:
    doc = read_asciidoc(b"[[the-id]]\n== A heading\n\ntext\n\n== Another one\n\ntext\n", "d")
    assert [s.anchor for s in doc.sections] == ["the-id", "another-one"]


def test_delimited_blocks_are_single_blocks_with_their_delimiters_dropped() -> None:
    text = "== S\n\nIntro line.\n\n----\n== not a heading\n\nstill the listing\n----\n\n....\nliteral\n....\n"
    doc = read_asciidoc(text.encode(), "d")
    assert doc.sections[0].units == ("Intro line.", "== not a heading\n\nstill the listing", "literal")


def test_an_unclosed_delimiter_runs_to_the_end_and_loses_no_text() -> None:
    doc = read_asciidoc(b"== S\n\n----\nline one\nline two\n", "d")
    assert doc.sections[0].units == ("line one\nline two",)


def test_list_terms_and_markers_start_blocks_without_a_blank_line() -> None:
    text = "== O\n\n-a::\n    First option.\n-b::\n    Second option.\n\n* one\n* two\n"
    units = read_asciidoc(text.encode(), "d").sections[0].units
    assert units == ("-a::\n    First option.", "-b::\n    Second option.", "* one", "* two")


def test_include_is_never_read_and_says_where_the_rest_is() -> None:
    doc = read_asciidoc(b"== S\n\ninclude::/etc/passwd[]\n\ninclude::config/core.adoc[]\n", "d")
    assert doc.sections[0].units == ("[include] /etc/passwd", "[include] config/core.adoc")


def test_conditionals_attributes_comments_and_block_attributes_are_dropped_and_counted() -> None:
    text = ":sectanchors:\n== S\n\n// a comment\nifdef::foo[]\nkept text\nendif::[]\n\n[verse]\nverse text\n"
    text += "\n////\nhidden\n////\n"
    doc = read_asciidoc(text.encode(), "d")
    assert doc.sections[0].units == ("kept text", "verse text")
    assert doc.warnings == ("2 ifdef/ifndef/ifeval/endif lines dropped; their content is kept unconditionally",)


def test_a_block_title_leads_its_block() -> None:
    doc = read_asciidoc(b"== S\n\n.Example output\n----\nok\n----\n", "d")
    assert doc.sections[0].units == (".Example output\nok",)


def test_text_before_any_heading_is_section_zero_titled_with_the_document() -> None:
    doc = read_asciidoc(b"= Title\n\nPreamble words.\n\n== S\n\nx\n", "d")
    assert doc.sections[0].id == "0" and doc.sections[0].title == "Title"
    assert doc.sections[0].units == ("Preamble words.",)


def test_a_1_mb_single_line_is_one_block() -> None:
    line = "w" * 1_000_000
    doc = read_asciidoc(f"== S\n\n{line}\n".encode(), "d")
    assert doc.sections[0].units == (line,)


@pytest.mark.parametrize("payload", [b"== S\n\nbad \x00 byte\n", b"== S\n\nbad \xff\xfe bytes\n"])
def test_nul_bytes_and_invalid_utf8_raise_liberror_with_a_hint(payload: bytes) -> None:
    with pytest.raises(LibError) as caught:
        read_asciidoc(payload, "d")
    assert caught.value.hint


def test_crlf_line_endings_read_like_lf() -> None:
    assert read(MANPAGE.replace("\n", "\r\n")) == read(MANPAGE)


def test_a_long_run_of_brackets_after_ifdef_is_linear() -> None:
    hostile = "ifdef::" + "[" * 200_000 + "\ninclude::" + "[" * 200_000 + "\n=" * 5 + "\n"
    start = time.perf_counter()
    read_asciidoc(hostile.encode(), "d")
    assert time.perf_counter() - start < 3


def test_every_non_heading_line_survives_in_some_block() -> None:
    text = "== S\n\nalpha beta\ngamma\n\n* delta\n\n----\nepsilon\n----\n"
    doc = read_asciidoc(text.encode(), "d")
    joined = "\n".join(doc.sections[0].units)
    for word in ("alpha beta", "gamma", "delta", "epsilon"):
        assert word in joined
