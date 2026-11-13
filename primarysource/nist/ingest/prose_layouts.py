"""Section splitting for NIST prose documents whose headings the generic splitter does not recognise.

``extract.split_sections`` reads headings that start a line.  Several families of NIST PDF do not satisfy that:

``numbered``       ``1 Introduction`` / ``1. Introduction`` chapters.  ``pdftotext`` often glues the chapter heading
                   after the page's running header (``This publication is available free of charge from: <doi>  1
                   Introduction``), which is why the generic splitter sees no ``1``.  Sub-headings (``1.1 Purpose``)
                   are indented but otherwise ordinary.
``numbered_zero``  ``1.0 Introduction`` chapters (id ``1``), sub-headings ``3.1 ...``.
``section_colon``  ``SECTION 1: INTRODUCTION`` chapters, ``1.1 Background`` sub-headings.
``chapter_word``   ``CHAPTER ONE`` chapters whose title is on the next line, all-caps ``1.1 TITLE`` sub-headings.

Every layout also reads appendices: ``Appendix A—Title``, ``Appendix A: Title``, ``APPENDIX A: TITLE``, a bare
``APPENDIX A`` with the title on the next line, and ``Appendix A Title`` when it opens a page.

The acceptance rule is the generic one: a heading counts only when it is the next child of a parent already seen,
so cross-references, footnotes and repeated page headers cannot become sections.  Documents with no numbered
headings at all (the annual reports, and the newer-format publications with unnumbered headings) are not split:
``detect_layout`` returns None for them, because any section id would have to be invented.
"""

from __future__ import annotations

import re

from primarysource.nist.models import Section

LAYOUTS: tuple[str, ...] = (
    "numbered",
    "numbered_zero",
    "section_colon",
    "chapter_word",
)

# pdftotext puts the running header and the first line of the page on one line.
_RUNNING_HEADER = re.compile(
    r"^\f?\s*This publication is available free of charge from:\s*\S+\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_LEADER = re.compile(r"\.{4,}|(?:\. ){4,}")
_MAX_HEADING = 120

_CHAPTER = re.compile(r"^(?P<id>\d+)\.?\s+(?P<heading>[A-Z].*)$")
_CHAPTER_ZERO = re.compile(r"^(?P<id>\d+)\.0\s+(?P<heading>[A-Z].*)$")
_SECTION_COLON = re.compile(r"^SECTION\s+(?P<id>\d+)\s*[:.]\s*(?P<heading>\S.*)$")
_CHAPTER_WORD = re.compile(
    r"^CHAPTER\s+(?P<word>ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE)\b\s*(?P<rest>.*)$"
)
_WORDS = "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE".split()
_SUB = re.compile(r"^(?P<id>(?:\d+|[A-Z])(?:\.\d+)+)\.?\s+(?P<heading>[A-Z0-9].*)$")
_APPENDIX_SEP = re.compile(
    r"^(?:Appendix|APPENDIX)\s+(?P<id>[A-Z])\s*[—–:.\-]+\s*(?P<heading>\S.*)$"
)
_APPENDIX_OPEN = re.compile(
    r"^(?:Appendix|APPENDIX)\s+(?P<id>[A-Z])\s+(?P<heading>[A-Z].*)$"
)
_APPENDIX_BARE = re.compile(r"^APPENDIX\s+(?P<id>[A-Z])$")

# A hit is (id, heading, number of extra lines consumed after the heading line).
_Hit = tuple[str, str, int]


def _clean_heading(heading: str) -> str | None:
    heading = heading.strip()
    if not heading or _LEADER.search(heading) or len(heading) > _MAX_HEADING:
        return None
    if heading.endswith(".") or heading.count("(") != heading.count(")"):
        return None  # table-of-contents row or running prose
    if re.search(r"\s{3,}PAGE\s+\d+$", heading):
        return None  # running page header, not a heading
    return heading


def _next_text(lines: list[str], index: int) -> str | None:
    """The next non-blank line after ``index``, stripped, or None when it is not close by."""
    for look in range(index + 1, min(index + 4, len(lines))):
        stripped = lines[look].strip()
        if stripped:
            return stripped
    return None


def _appendix_hit(
    text: str, opens_page: bool, lines: list[str], index: int
) -> _Hit | None:
    m = _APPENDIX_SEP.match(text)
    if m is None and opens_page:
        m = _APPENDIX_OPEN.match(text)
    if m is not None:
        heading = _clean_heading(m.group("heading"))
        return (m.group("id"), heading, 0) if heading else None
    m = _APPENDIX_BARE.match(text)
    if m is not None:
        following = _next_text(lines, index)
        heading = _clean_heading(following) if following else None
        return (m.group("id"), heading, 1) if heading else None
    return None


def _top_level(layout: str, text: str, lines: list[str], index: int) -> _Hit | None:
    if layout == "chapter_word":
        m = _CHAPTER_WORD.match(text)
        if m is None:
            return None
        number = str(_WORDS.index(m.group("word")) + 1)
        rest = m.group("rest").strip()
        if rest and not rest.startswith("PAGE"):
            heading = _clean_heading(rest)
            return (number, heading, 0) if heading else None
        if rest:
            return None  # "CHAPTER TWO   PAGE 6" running header
        following = _next_text(lines, index)
        heading = _clean_heading(following) if following else None
        return (number, heading, 1) if heading else None
    pattern = {
        "numbered": _CHAPTER,
        "numbered_zero": _CHAPTER_ZERO,
        "section_colon": _SECTION_COLON,
    }[layout]
    m = pattern.match(text)
    if m is None:
        return None
    heading = _clean_heading(m.group("heading"))
    if heading is None:
        return None
    if layout == "numbered" and "  " in heading:
        return None  # a table row: columns are separated by runs of spaces
    return m.group("id"), heading, 0


def _match(
    layout: str, line: str, lines: list[str], index: int
) -> tuple[_Hit, bool] | None:
    """Match one line: the hit, and whether the line opens a page (heading glued after the running header)."""
    opens_page = False
    header = _RUNNING_HEADER.match(line)
    if header is not None:
        opens_page = True
        line = header.group("rest")
    text = line.strip().lstrip("\f").strip()
    if not text:
        return None
    hit = _appendix_hit(text, opens_page, lines, index)
    if hit is None:
        hit = _top_level(layout, text, lines, index)
    if hit is not None:
        return hit, opens_page
    m = _SUB.match(text)
    if m is None:
        return None
    heading = _clean_heading(m.group("heading"))
    return ((m.group("id"), heading, 0), opens_page) if heading else None


def _ordinal(part: str) -> int:
    return int(part) if part.isdigit() else ord(part) - ord("A") + 1


def _parent_key(sec_id: str) -> str:
    parent, _, _ = sec_id.rpartition(".")
    if parent:
        return parent
    return "#appendix" if sec_id.isalpha() else "#chapter"


def _is_next(sec_id: str, last_child: dict[str, int]) -> bool:
    key = _parent_key(sec_id)
    if key not in last_child and not key.startswith("#"):
        return False
    return _ordinal(sec_id.rpartition(".")[2]) == last_child.get(key, 0) + 1


def split_for_layout(text: str, layout: str) -> tuple[Section, ...]:
    """Split ``text`` into sections using the heading conventions of ``layout`` (one of ``LAYOUTS``).

    Lines are numbered from 1 and split on newline only.  Sections do not nest: each runs from its heading line
    to the line before the next heading, the last to the end of the text.
    """
    if layout not in LAYOUTS:
        raise ValueError(
            f"unknown layout {layout!r}; expected one of {', '.join(LAYOUTS)}"
        )
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    matches = [
        (index, m)
        for index, line in enumerate(lines)
        if (m := _match(layout, line, lines, index))
    ]
    # A bare chapter number ("3 Administrators should consult ...") also starts a footnote.  Where a chapter
    # number has a candidate at the top of a page, behind the running header, that one is the heading and the
    # others are dropped; otherwise a footnote met first would take the chapter's place in the sibling order.
    page_openers = {
        hit[0]
        for _, (hit, opens) in matches
        if opens and layout == "numbered" and hit[0].isdigit()
    }
    found: list[tuple[str, str, int]] = []
    last_child: dict[str, int] = {}
    for index, (hit, opens_page) in matches:
        sec_id, heading, _ = hit
        if layout == "numbered" and sec_id in page_openers and not opens_page:
            continue
        if not _is_next(sec_id, last_child):
            continue
        key = _parent_key(sec_id)
        last_child[key] = last_child.get(key, 0) + 1
        last_child.setdefault(sec_id, 0)
        found.append((sec_id, heading, index + 1))
    sections: list[Section] = []
    for position, (sec_id, heading, start) in enumerate(found):
        end = found[position + 1][2] - 1 if position + 1 < len(found) else len(lines)
        sections.append(
            Section(id=sec_id, heading=heading, start_line=start, end_line=end)
        )
    return tuple(sections)


MIN_SECTIONS = 3


def detect_layout(text: str) -> str | None:
    """Name the layout that finds the most sections in ``text``, or None when none finds ``MIN_SECTIONS``.

    The layouts are mutually exclusive in practice: each one's chapters are the only parents the others'
    sub-headings would accept, so a document written one way yields nothing under the others.  A document with
    no numbered headings (an annual report, an unnumbered newer-format publication) yields None.
    """
    best: str | None = None
    best_count = MIN_SECTIONS - 1
    for layout in LAYOUTS:
        count = len(split_for_layout(text, layout))
        if count > best_count:
            best, best_count = layout, count
    return best
