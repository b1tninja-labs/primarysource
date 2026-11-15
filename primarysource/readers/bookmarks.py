"""Cut a bookmarked document's page texts into numbered sections of sentences (`cl.segment_bookmarks`).

Backend-independent: it takes the page texts and the flattened bookmark outline that a reader produced
(`primarysource.readers.pdf`) and never opens a file. Lifted from the ecma collection's private reader
(`primarysource/ecma/_pdf.py`), whose tests moved with it.

- a bookmark whose title starts with a clause number (`5.3 Separator characters`, `A.2.1 Data Types`) or
  `Annex A` gets that number as its id (`5.3`, `A.2.1`, `A`), an `Appendix I` bookmark gets `Appendix-I`, any
  other (`Bibliography`) its slug;
- page furniture (a header or footer line that repeats on many pages, once digits and Roman numerals are
  ignored) is dropped before anything is cut;
- a section's text runs from its heading to the next bookmark's heading, subsections excluded, and is split
  into sentences, because a PDF gives sentences and not paragraphs (`Unit.SENTENCE`).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from typing import Any

_NUMBERED = re.compile(r"^(?P<id>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.*)$")
_LETTERED = re.compile(r"^(?P<id>[A-Z](?:\.\d+)+)\.?\s+(?P<title>\S.*)$")
_ANNEX = re.compile(r"^(?:Annex|Appendix)\s+(?P<id>[A-Z0-9]+(?:\.\d+)*)\b[.:]?\s*(?P<title>.*)$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+(?:\s+of\s+\d+)?")
_ROMAN = re.compile(r"^(?:[ivxlcdm]+\s+)|(?:\s+[ivxlcdm]+)$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'•])")
_ABBREV = ("e.g.", "i.e.", "etc.", "vs.", "cf.", "No.", "Fig.", "Sec.", "approx.")

Outline = list[tuple[str, int, int]]
"""A bookmark tree flattened to (title, 0-based page, depth), in document order."""


def slug(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "section"


def split_sentences(text: str) -> list[str]:
    """Sentences of already-flowed text: split after . ! ? before a capital, digit or bracket, not after the
    abbreviations in `_ABBREV`."""
    flowed = " ".join(text.split())
    if not flowed:
        return []
    parts = _SENTENCE_END.split(flowed)
    out: list[str] = []
    for part in parts:
        if out and out[-1].endswith(_ABBREV):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def furniture_key(line: str) -> str:
    """A line with its digits and leading or trailing Roman numerals folded away, so a running header or footer
    gives the same key on every page."""
    key = _DIGITS.sub("#", line.strip())
    key = _ROMAN.sub("", key).strip()
    return re.sub(r"\s+", " ", key)


def heading_id(title: str) -> tuple[str, str]:
    """The section id and the title text a bookmark title gives (see the module docstring)."""
    for pattern in (_NUMBERED, _LETTERED, _ANNEX):
        match = pattern.match(title)
        if match:
            ident = match.group("id").upper() if pattern is not _NUMBERED else match.group("id")
            if pattern is _ANNEX and title.lower().startswith("appendix"):
                ident = f"Appendix-{ident}"
            return ident, match.group("title").strip() or title
    return slug(title), title


_TRACKING_MARK = re.compile(r"^\s*[-`,]{8,}")
"""A distributor's tracking string printed before the first line of a page (``--`,``,``,,,`---1 Scope``)."""


def clean_pages(pages: list[str], *, keep_spacing: bool = False) -> list[list[str]]:
    """Each page's non-empty lines with page furniture dropped: a line whose `furniture_key` occurs on at least a
    quarter of the pages (at least 3) is a running header or footer. Whitespace is collapsed unless `keep_spacing`
    (layout text, whose column gaps the numbered-heading splitter reads); a distributor's tracking string at the
    start of a line is removed either way."""

    def tidy(raw: str) -> str:
        line = _TRACKING_MARK.sub("", raw)
        return line.rstrip() if keep_spacing else " ".join(line.split())

    per_page = [[ln for ln in (tidy(raw) for raw in text.splitlines()) if ln.strip()] for text in pages]
    seen: Counter[str] = Counter()
    for lines in per_page:
        seen.update({furniture_key(" ".join(ln.split())) for ln in lines})
    limit = max(3, len(pages) // 4)
    return [[ln for ln in lines if seen[furniture_key(" ".join(ln.split()))] < limit] for lines in per_page]


def cut_numbered(pages: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Cut page texts into sections at numbered headings, for a PDF without bookmarks (older ISO editions, for
    one). Furniture is dropped as in `cut`, then the shared numbered-heading splitter
    (`primarysource.pdfcorpus.split.split_sections`, `cl.segment_numbered`) finds the headings. Text before the
    first heading becomes a `front-matter` section. Returns the sections in `cut`'s shape and how many headings
    were found."""
    from primarysource.pdfcorpus.split import split_sections

    lines: list[str] = []
    page_of: list[int] = []
    for number, page_lines in enumerate(clean_pages(pages, keep_spacing=True)):
        lines.extend(page_lines)
        page_of.extend([number] * len(page_lines))
    found = split_sections("\n".join(lines))
    sections: list[dict[str, Any]] = []
    first = found[0].start_line - 1 if found else len(lines)
    if first > 0:
        sections.append(
            {
                "id": "front-matter",
                "title": "Front matter",
                "depth": 0,
                "page": 1,
                "text": "\n".join(split_sentences(" ".join(lines[:first]))),
            }
        )
    used: Counter[str] = Counter()
    for section in found:
        ident = section.id
        used[ident] += 1
        if used[ident] > 1:
            ident = f"{ident}-{used[ident] - 1}"
        body = lines[section.start_line : section.end_line]
        sections.append(
            {
                "id": ident,
                "title": " ".join(section.heading.split()),
                "depth": section.id.count("."),
                "page": page_of[section.start_line - 1] + 1,
                "text": "\n".join(split_sentences(" ".join(body))),
            }
        )
    return sections, len(found)


def cut(pages: list[str], outline: Outline, *, front_matter: bool = False) -> tuple[list[dict[str, Any]], int]:
    """Cut page texts into sections at the bookmarked headings. Returns the sections
    (`{"id", "title", "depth", "page", "text"}`, `page` 1-based, `text` the sentences joined by newlines) and how
    many headings were found as a line of text (the rest fall back to the start of their page). With `front_matter`,
    text before the first heading (a cover, a notice) becomes a leading `front-matter` section."""
    count = len(pages)
    cleaned = ["\n".join(lines) for lines in clean_pages(pages)]
    starts: list[int] = []
    joined = ""
    for text in cleaned:
        starts.append(len(joined))
        joined += text + "\n"

    spots: list[tuple[int, int]] = []  # (start, end) of each heading's line in `joined`, never moving backwards
    cursor = 0
    located = 0
    for heading, page, _ in outline:
        ident, text_title = heading_id(heading)
        numbered = _NUMBERED.match(heading) or _LETTERED.match(heading)
        words = r"\s+".join(re.escape(w) for w in (text_title if numbered else heading).split())
        number = re.escape(ident) if numbered else ""
        pattern = re.compile(rf"(?m)^{number}\.?\s*{words}" if number else rf"(?m)^{words}")
        first = min(page, count - 1)
        base = max(starts[first], cursor)
        found = pattern.search(joined, base, starts[first + 1] if first + 1 < count else len(joined))
        if found is None:
            found = pattern.search(joined, base)
        if found is not None:
            located += 1
        spot = (found.start(), found.end()) if found else (base, base)
        spots.append(spot)
        cursor = max(cursor, spot[0])
    sections: list[dict[str, Any]] = []
    used: Counter[str] = Counter()
    if front_matter and outline and joined[: spots[0][0]].strip():
        front = split_sentences(joined[: spots[0][0]])
        text = "\n".join(front)
        sections.append({"id": "front-matter", "title": "Front matter", "depth": 0, "page": 1, "text": text})
    for n, (heading, page, depth) in enumerate(outline):
        ident, text_title = heading_id(heading)
        used[ident] += 1
        if used[ident] > 1:
            ident = f"{ident}-{used[ident] - 1}"
        begin = spots[n][1]
        stop = spots[n + 1][0] if n + 1 < len(outline) else len(joined)
        sections.append(
            {
                "id": ident,
                "title": text_title,
                "depth": depth,
                "page": page + 1,
                "text": "\n".join(split_sentences(joined[begin : max(begin, stop)])),
            }
        )
    return sections, located


_GAP = re.compile(r"\s{2,}")
TITLE_WIDTH = 80


def table_lines(text: str) -> list[str]:
    """The lines of one page of layout text, each a unit: leading and trailing space removed and every run of two
    or more spaces (a column gap in a table) shown as ` | `. Blank lines are dropped."""
    return [" | ".join(_GAP.split(line.strip())) for line in text.splitlines() if line.strip()]


def cut_pages(
    pages: list[str],
    per_section: int = 1,
    title_of: Callable[[int, int, list[str]], str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Cut page texts into one section per page (or per `per_section` pages), for a PDF that is tables, not prose
    (the GM parameter files). Furniture is dropped as in `cut`; each page's remaining lines are the section's
    units (`table_lines`), because a table row has no sentence ends. The id is `p<first page>`, or `p<first>-<last>`
    for a span, the title is `title_of(first, last, lines)` or else the first line of text (at most `TITLE_WIDTH`
    characters), and a page with no text after cleaning is left out. Returns the sections in `cut`'s shape and the
    number of pages that had no text at all (a scanned page has none)."""
    if per_section < 1:
        raise ValueError("per_section is at least 1")
    kept = clean_pages(pages, keep_spacing=True)
    empty = sum(1 for text in pages if not text.strip())
    sections: list[dict[str, Any]] = []
    for first in range(0, len(pages), per_section):
        last = min(first + per_section, len(pages)) - 1
        units = [unit for lines in kept[first : last + 1] for unit in table_lines("\n".join(lines))]
        if not units:
            continue
        ident = f"p{first + 1}" if last == first else f"p{first + 1}-{last + 1}"
        title = title_of(first + 1, last + 1, units) if title_of is not None else ""
        if not title:
            title = units[0] if len(units[0]) <= TITLE_WIDTH else units[0][: TITLE_WIDTH - 3] + "..."
        sections.append({"id": ident, "title": title, "depth": 0, "page": first + 1, "text": "\n".join(units)})
    return sections, empty
