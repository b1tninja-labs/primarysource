"""The reStructuredText reader over invented documents, hostile input included. No real text."""

from __future__ import annotations

import time

import pytest

from primarysource.errors import LibError
from primarysource.pkgdocs.readers.rst import read_rst


def shape(text: str, **kw: str) -> list[tuple[str, str, int]]:
    doc = read_rst(text.encode(), "d", **kw)
    return [(s.id, s.title, s.depth) for s in doc.sections]


def test_levels_follow_first_appearance_not_the_character() -> None:
    text = "Alpha\n=====\n\na\n\nBeta\n----\n\nb\n\nGamma\n~~~~~\n\nc\n\nDelta\n=====\n\nd\n"
    assert shape(text) == [("1", "Alpha", 1), ("1.1", "Beta", 2), ("1.1.1", "Gamma", 3), ("2", "Delta", 1)]
    swapped = "Alpha\n-----\n\na\n\nBeta\n=====\n\nb\n\nGamma\n-----\n\nc\n"
    assert shape(swapped) == [("1", "Alpha", 1), ("1.1", "Beta", 2), ("2", "Gamma", 1)]


def test_an_overline_style_differs_from_an_underline_only_style() -> None:
    text = "=====\nTop\n=====\n\nintro\n\nOne\n===\n\nx\n\nTwo\n===\n\ny\n"
    doc = read_rst(text.encode(), "d", "T")
    assert doc.title == "T"
    assert [(s.id, s.title, s.depth) for s in doc.sections] == [("0", "Top", 1), ("1", "One", 2), ("2", "Two", 2)]


def test_a_short_underline_is_not_a_heading() -> None:
    doc = read_rst(b"A long title line\n===\n\nbody\n", "d")
    assert [s.title for s in doc.sections] == ["d"]
    assert "A long title line\n===" in doc.sections[0].units[0]


def test_a_literal_block_holding_an_adornment_like_line_is_not_a_heading() -> None:
    text = "Intro paragraph::\n\n    Not a title\n    ===========\n\nAfter.\n\nReal\n====\n\nx\n"
    doc = read_rst(text.encode(), "d")
    assert [s.title for s in doc.sections] == ["d", "Real"]
    assert doc.sections[0].units == ("Intro paragraph::", "Not a title\n===========", "After.")


def test_a_directive_and_its_body_are_one_block_prefixed_with_its_name() -> None:
    text = "T\n==\n\n.. code-block:: python\n   :linenos:\n\n   x = 1\n   y = 2\n\nafter\n"
    doc = read_rst(text.encode(), "d")
    assert doc.sections[0].units == ("[code-block] python\n:linenos:\n\nx = 1\ny = 2", "after")


def test_include_and_raw_directives_are_inert_text_and_no_path_is_opened() -> None:
    doc = read_rst(b"T\n==\n\n.. include:: /etc/passwd\n\n.. literalinclude:: ../../secret\n   :language: c\n", "d")
    assert doc.sections[0].units == ("[include] /etc/passwd", "[literalinclude] ../../secret\n:language: c")


def test_comments_targets_and_substitutions_are_dropped_and_a_label_becomes_the_anchor() -> None:
    text = (
        "T\n==\n\n.. a comment\n   spanning lines\n\n.. |x| replace:: y\n\n.. _s-sample:\n\nSample\n------\n\nbody\n"
    )
    doc = read_rst(text.encode(), "d")
    assert [s.anchor for s in doc.sections] == ["t", "s-sample"]
    assert doc.sections[0].units == ()


def test_a_chapter_title_is_promoted_and_base_numbers_its_subsections() -> None:
    text = "Chapter title\n=============\n\nlead\n\nFirst\n-----\n\na\n\nDeeper\n~~~~~~\n\nb\n\nSecond\n------\n\nc\n"
    doc = read_rst(text.encode(), "ch", base="5")
    assert doc.title == "Chapter title"
    assert [(s.id, s.title, s.depth) for s in doc.sections] == [
        ("5", "Chapter title", 1),
        ("5.1", "First", 2),
        ("5.1.1", "Deeper", 3),
        ("5.2", "Second", 2),
    ]
    assert doc.sections[0].units == ("lead",)


def test_list_items_fields_and_definitions_are_one_block_each() -> None:
    text = (
        "T\n==\n\n- first item\n  continued\n- second item\n\n:Key: value\n:Other: more\n\nterm\n    its definition\n"
    )
    assert read_rst(text.encode(), "d").sections[0].units == (
        "- first item\n  continued",
        "- second item",
        ":Key: value",
        ":Other: more",
        "term\n    its definition",
    )


def test_footnotes_and_tables_are_blocks() -> None:
    text = "T\n==\n\n.. [#] A note.\n\n+---+---+\n| a | b |\n+---+---+\n\n=== ===\nx   y\n=== ===\n"
    units = read_rst(text.encode(), "d").sections[0].units
    assert units[0] == "[footnote #] A note."
    assert units[1].startswith("+---+") and units[2].startswith("=== ===")


def test_inline_literals_and_roles_are_cleaned_in_titles_only() -> None:
    doc = read_rst(b"``code`` and :pep:`440`\n=======================\n\nUse ``x``.\n", "d")
    assert doc.sections[0].title == "code and 440"
    assert doc.sections[0].units == ("Use ``x``.",)


def test_deeply_nested_indentation_does_not_recurse() -> None:
    text = "T\n==\n\n" + "\n".join(" " * n + "level" for n in range(1, 5001)) + "\n"
    start = time.perf_counter()
    doc = read_rst(text.encode(), "d")
    assert time.perf_counter() - start < 3
    assert sum(len(s.units) for s in doc.sections) >= 1


def test_tabs_and_crlf_read_like_spaces_and_lf() -> None:
    text = "T\n==\n\nfirst\n\n\tquoted\n"
    assert shape(text) == shape(text.replace("\n", "\r\n"))
    assert read_rst(text.encode(), "d").sections[0].units == ("first", "quoted")


@pytest.mark.parametrize("payload", [b"T\n==\n\na\x00b\n", b"T\n==\n\n\xc3\x28\n"])
def test_nul_bytes_and_invalid_utf8_raise_liberror_with_a_hint(payload: bytes) -> None:
    with pytest.raises(LibError) as caught:
        read_rst(payload, "d")
    assert caught.value.hint


def test_a_million_character_line_and_a_hostile_table_border_are_linear() -> None:
    text = "T\n==\n\n" + "x" * 1_000_000 + "\n\n" + "=" * 100_000 + " " * 100_000 + "x\n"
    start = time.perf_counter()
    read_rst(text.encode(), "d")
    assert time.perf_counter() - start < 3
