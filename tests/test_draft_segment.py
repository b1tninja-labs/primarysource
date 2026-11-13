"""Segmenting a draft's text: ids, line coordinates, page furniture, the cache, and hostile input."""

from __future__ import annotations

import time

import pytest
from draft_fixture import build_txt

from primarysource.draft import segment
from primarysource.errors import LibError


def test_sections_get_ids_a_ref_can_carry() -> None:
    seg = segment.segment(build_txt())
    assert [s.id for s in seg.sections] == [
        "abstract", "status-of-this-memo", "copyright-notice", "1", "2", "2.1", "2.2", "3", "4", "5", "5.1", "A",
        "author-s-address",
    ]  # fmt: skip
    appendix = seg.section("A")
    assert appendix is not None
    assert (appendix.num, appendix.title) == ("Appendix A", "Worked Example")
    assert seg.method == "toc"


def test_a_page_break_inside_a_paragraph_neither_leaks_furniture_nor_splits_it() -> None:
    seg = segment.segment(build_txt())
    everything = [b.text for s in seg.sections for b in s.blocks]
    assert not [t for t in everything if "[Page" in t or t.startswith(("Internet-Draft", "RFC 0"))]
    intro = seg.section("1")
    assert intro is not None
    assert [b.text.split()[0] for b in intro.blocks] == ["The", "A"]
    assert intro.blocks[1].text.startswith("A second paragraph says that every sprocket MUST")
    assert "\n" not in intro.blocks[1].text


def test_a_figure_is_one_block_of_its_own_kind() -> None:
    messages = segment.segment(build_txt()).section("2.1")
    assert messages is not None
    assert [b.kind for b in messages.blocks] == ["t", "artwork", "t"]


def test_line_numbers_are_the_files_line_numbers_whatever_the_line_endings() -> None:
    plain = build_txt()
    lines = plain.replace("\f", "").split("\n")
    seg = segment.segment(plain)
    intro = seg.section("1")
    assert intro is not None
    first = intro.blocks[0]
    assert lines[first.start - 1].strip() == first.text
    for variant in (plain.replace("\n", "\r\n"), plain.replace("\n", "\r"), "﻿" + plain):
        again = segment.segment(variant)
        assert [(s.id, [(b.start, b.end) for b in s.blocks]) for s in again.sections] == [
            (s.id, [(b.start, b.end) for b in s.blocks]) for s in seg.sections
        ]


def test_the_exotic_line_separators_python_would_split_on_do_not_move_the_lines() -> None:
    text = build_txt().replace("sprocket MUST", "sprocket\x0b\x1c\x85 MUST")
    assert [s.id for s in segment.segment(text).sections] == [s.id for s in segment.segment(build_txt()).sections]
    assert len(segment.normalise(text)) == len(segment.normalise(build_txt()))


def test_duplicate_headings_get_distinct_ids() -> None:
    used: set[str] = set()
    assert [segment.section_id("", "Acknowledgments", used) for _ in range(3)] == [
        "acknowledgments", "acknowledgments-2", "acknowledgments-3",
    ]  # fmt: skip
    assert segment.section_id("", "!!!", used) == "section"
    assert segment.section_id("Appendix B", "x", used) == "B"


def test_a_draft_with_no_headings_is_one_section_not_nothing() -> None:
    seg = segment.segment("just words\n\nand more words\n")
    assert len(seg.sections) == 1
    joined = " ".join(b.text for s in seg.sections for b in s.blocks)
    assert "just words" in joined and "and more words" in joined
    assert [(b.start, b.end) for s in seg.sections for b in s.blocks] == [(1, 1), (3, 3)]


def test_the_cache_round_trips_and_a_stale_or_damaged_one_is_ignored() -> None:
    seg = segment.segment(build_txt())
    assert segment.Segmented.from_json(seg.to_json()) == seg
    stale = seg.to_json().replace(f'"parser": "{segment.PARSER_VERSION}"', '"parser": "0"')
    assert segment.Segmented.from_json(stale) is None
    assert segment.Segmented.from_json("{not json") is None
    assert segment.Segmented.from_json(f'{{"parser": "{segment.PARSER_VERSION}"}}') is None


def test_text_that_is_not_a_text_draft_is_refused_before_the_segmenter_sees_it() -> None:
    with pytest.raises(LibError, match="NUL"):
        segment.decode(b"abc\x00def")
    with pytest.raises(LibError, match="limit"):
        segment.decode(b"a" * (segment.MAX_TEXT_BYTES + 1))
    with pytest.raises(LibError, match="characters"):
        segment.segment("x" * (segment.MAX_LINE + 1))
    with pytest.raises(LibError, match="line limit"):
        segment.segment("x\n" * (segment.MAX_LINES + 1))


def test_latin_1_text_from_an_old_draft_is_decoded_not_rejected() -> None:
    text, encoding = segment.decode("Müller".encode("latin-1"))
    assert (text, encoding) == ("Müller", "latin-1")
    assert segment.decode("Müller".encode())[1] == "utf-8"


@pytest.mark.parametrize(
    "hostile",
    [
        "Table of Contents\n\n" + "   1.  Intro " + ". " * 900 + " 2\n\n1.  Intro\n\n   x\n",
        "Abstract\n\n   1.  " + " " * 1900 + "x\n",
        "\n".join("1." * 900 for _ in range(200)),
        "Table of Contents\n" + ("   1.  A" + " . " * 600 + "\n") * 300,
        "".join(f"   {i}.  Title {i} " + ". " * 30 + f"  {i}\n" for i in range(1, 3000)),
    ],
    ids=["long-leader", "long-spaces", "dotted-numbers", "many-leaders", "huge-toc"],
)
def test_pathological_text_finishes_quickly(hostile: str) -> None:
    started = time.monotonic()
    segment.segment(hostile)
    assert time.monotonic() - started < 5
