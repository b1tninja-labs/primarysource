"""Three txtseg gaps found by comparing the text segmenter with RFCXML over every RFC that has both.

- A real title the title gate refused: one led by '<' (rfc9022 4.6.2.1) or a comma title under a multi-level number
  (rfc9788 C.1.2.1). Numbered prose in old RFCs must still be refused.
- Section numbers deeper than six levels (rfc8878 3.1.1.3.2.1.1).
- A quoted document's numbering listed under an appendix in the contents (rfc9592 Appendix A).

Invented text throughout.
"""

from __future__ import annotations

from primarysource.rfc.index.txtseg import find_headings, parse_toc

TITLES = """Table of Contents

   1.  Introduction
   2.  Elements
   3.  Security Considerations

1.  Introduction

   This invented memo exists for a test.

2.  Elements

   The elements follow.

2.1.  Element Forms

   Forms are invented.

2.1.1.  <ex:widget> Element

   The widget element is invented.

2.1.2.  Signed-Only Widgets over a Simple Channel, No Header

   Signed-only widgets are invented.

3.  Security Considerations

   None.
"""


def test_angle_bracket_and_multilevel_comma_titles_are_headings() -> None:
    heads, _, _ = find_headings(TITLES.split("\n"))
    found = {h[1]: h[2] for h in heads}
    assert found["2.1.1"] == "<ex:widget> Element"
    assert found["2.1.2"] == "Signed-Only Widgets over a Simple Channel, No Header"


LEGACY_PROSE = """Network Working Group                                          A. Writer
Request for Comments: 9999                                     March 1990

1.  Introduction

   This invented memo has no contents and a numbered list of prose.

2.  Requirements

   The cases are:

   1.  Any channel supporting widgets.

   2.  Any mapping of widgets onto gadgets (usually gadget(80)), where a gadget is
       also a widget.

3.  Approach

   The approach is invented.
"""


def test_single_level_prose_with_a_comma_does_not_take_a_heading_slot() -> None:
    heads, quality, _ = find_headings(LEGACY_PROSE.split("\n"))
    assert quality.method == "scan"
    assert [h[1] for h in heads if h[1]] == ["1", "2", "3"]


def test_a_relaxed_title_ending_on_a_connective_is_wrapped_prose() -> None:
    memo = TITLES.replace(
        "2.1.2.  Signed-Only Widgets over a Simple Channel, No Header",
        "2.1.2.  The widget size can change over time, and",
    )
    heads, _, _ = find_headings(memo.split("\n"))
    assert "2.1.2" not in [h[1] for h in heads]


DEEP = """Table of Contents

   1.  Introduction
   2.  Frames
   3.  Security Considerations

1.  Introduction

   This invented memo exists for a test.

2.  Frames

   Frames are invented.

2.1.  Frame Layout

   The layout is invented.

2.1.1.  Blocks

   Blocks are invented.

2.1.1.1.  Block Kinds

   Kinds are invented.

2.1.1.1.1.  Literal Blocks

   Literal blocks are invented.

2.1.1.1.1.1.  Literal Headers

   Headers are invented.

2.1.1.1.1.1.1.  Literal Header Sizes

   Sizes are invented.

3.  Security Considerations

   None.
"""


def test_a_seventh_level_section_is_a_heading() -> None:
    heads, _, _ = find_headings(DEEP.split("\n"))
    assert "2.1.1.1.1.1.1" in [h[1] for h in heads]


QUOTED = """Table of Contents

   1.  Introduction
   2.  Retirement
   3.  Security Considerations
   Appendix A.  The Last Edition of the Guide
     1 Introduction
       1.1 Abbreviations Used in the Guide
     2 What Is the Group?
   Appendix B.  Acknowledgements

1.  Introduction

   This invented memo retires an invented guide.
"""


def test_numbers_under_an_appendix_in_the_contents_are_unnumbered() -> None:
    entries, _, _ = parse_toc(QUOTED.split("\n"))
    assert (entries[0].sec_num, entries[0].title) == ("1", "Introduction")  # the memo's own section 1
    by_title = {e.title: e.sec_num for e in entries[1:]}
    assert by_title["Abbreviations Used in the Guide"] == ""
    assert by_title["What Is the Group?"] == ""
    assert by_title["Retirement"] == "2"


def test_numbered_entries_after_the_quoted_span_keep_their_numbers() -> None:
    # back at the appendix's own indent, the quoted span has ended
    memo = QUOTED.replace("   Appendix B.  Acknowledgements", "   4.  Late Section")
    entries, _, _ = parse_toc(memo.split("\n"))
    assert {e.title: e.sec_num for e in entries}["Late Section"] == "4"
