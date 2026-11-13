"""The core Markdown reader (`cl.reader_markdown`), over invented documents. Moved from `tests/test_c2sp.py` with
the reader."""

from __future__ import annotations

import pytest
from c2sp_fixture import DOCS

from primarysource.errors import LibError
from primarysource.readers import markdown


def test_front_matter_title_headings_and_levels() -> None:
    doc = markdown.parse(DOCS["invented-log"])
    assert doc.front == {"description": "An invented log protocol"}
    assert doc.title == "The Invented Log"
    assert [(h.title, h.level) for h in doc.headings] == [
        ("The Invented Log", 1),
        ("Log Entries", 2),
        ("Entry Format: Details", 3),
        ("Another: Section", 2),
        ("Log Entries", 2),
        ("Setext Heading", 2),
    ]
    assert doc.preamble == ("> [!WARNING]\n> This is the editor's copy of an invented specification.",)


def test_a_fence_is_one_block_and_hides_its_hashes() -> None:
    doc = markdown.parse(DOCS["invented-log"])
    entries = doc.headings[1]
    fenced = [u for u in entries.units if u.startswith("```")]
    assert (
        len(fenced) == 1
        and "# not a heading, inside a fence" in fenced[0]
        and "\n\nstill the same block" in fenced[0]
    )
    assert "not a heading" not in [h.title for h in doc.headings]


def test_a_section_span_includes_subsections_and_excludes_its_own_heading() -> None:
    entries = markdown.parse(DOCS["invented-log"]).headings[1]
    assert entries.units[0].startswith("First entry paragraph")
    assert "### Entry Format: Details" in entries.units  # the subsection heading is a block of the parent's span
    assert entries.units[-1] == "Closing paragraph of the details."
    assert "Text of the colon-titled section." not in entries.units


def test_titles_lose_markup_and_slugs_are_unique() -> None:
    doc = markdown.parse("# A [link](http://x.invalid) and `code` *here*\n\n## Same\n\n## Same\n")
    assert doc.headings[0].title == "A link and code here"
    assert [h.slug for h in doc.headings[1:]] == ["same", "same-1"]
    assert markdown.slugify("Entry Format: Details") == "entry-format-details"


def test_setext_headings_and_crlf_and_an_unclosed_fence() -> None:
    doc = markdown.parse(b"Title\r\n=====\r\n\r\ntext\r\n\r\n```\r\nnever closed\r\n\r\nstill code\r\n")
    assert [h.title for h in doc.headings] == ["Title"]
    assert doc.headings[0].units == ("text", "```\nnever closed\n\nstill code\n")


def test_hostile_markdown_is_refused_not_truncated() -> None:
    with pytest.raises(LibError, match="NUL"):
        markdown.parse(b"# T\n\nbad \x00 byte\n")
    with pytest.raises(LibError, match="UTF-8"):
        markdown.parse(b"# T\n\n\xff\xfe\n")
    with pytest.raises(LibError, match="line over"):
        markdown.parse("# T\n\n" + "x" * (markdown.MAX_LINE + 1))
    with pytest.raises(LibError, match="bound"):
        markdown.parse(b"x" * (markdown.MAX_BYTES + 1))
    with pytest.raises(LibError, match="headings"):
        markdown.parse("\n".join(f"# h{i}" for i in range(markdown.MAX_SECTIONS + 1)))


def test_html_and_scripts_are_text_never_interpreted() -> None:
    doc = markdown.parse('# T\n\n<script>alert(1)</script>\n\n<img src="file:///etc/passwd">\n')
    assert doc.headings[0].units == ("<script>alert(1)</script>", '<img src="file:///etc/passwd">')
