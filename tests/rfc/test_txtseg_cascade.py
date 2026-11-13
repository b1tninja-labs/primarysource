"""txtseg must not drop a heading that is followed directly by its own child, nor that heading's descendants.

Found by comparing the text segmenter with RFCXML over every RFC that has both (docs/validation.md): 41 headings
were rejected this way and 194 descendants went with them (rfc9288 line 338 lost 174 sections). Invented text.
"""

from __future__ import annotations

from primarysource.rfc.index.txtseg import find_headings

MEMO = """Table of Contents

   1.  Introduction
   2.  Widgets
   3.  Gadgets
   4.  Security Considerations

1.  Introduction

   This invented memo exists for a test.

2.  Widgets

2.1.  Round Widgets

2.1.1.  Small Round Widgets

   Small round widgets are invented.

2.1.2.  Large Round Widgets

   Large round widgets are invented too.

3.  Gadgets

   Gadgets are invented.

4.  Security Considerations

   None.
"""


def test_a_heading_followed_by_its_child_keeps_itself_and_its_children() -> None:
    heads, quality, _ = find_headings(MEMO.split("\n"))
    assert quality.method == "toc"
    assert [h[1] for h in heads] == ["1", "2", "2.1", "2.1.1", "2.1.2", "3", "4"]


def test_a_heading_followed_by_an_unrelated_heading_is_still_rejected() -> None:
    # "2.1" followed directly by "3." is a numbered line, not a section with a body, so it stays out
    memo = MEMO.replace("2.1.1.  Small Round Widgets", "3.1.  Not A Child").replace(
        "2.1.2.  Large Round Widgets\n\n   Large round widgets are invented too.\n\n", ""
    )
    heads, _, _ = find_headings(memo.split("\n"))
    assert "2.1" not in [h[1] for h in heads]
