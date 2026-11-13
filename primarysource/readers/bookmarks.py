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


def cut(pages: list[str], outline: Outline) -> tuple[list[dict[str, Any]], int]:
    """Cut page texts into sections at the bookmarked headings. Returns the sections
    (`{"id", "title", "depth", "page", "text"}`, `page` 1-based, `text` the sentences joined by newlines) and how
    many headings were found as a line of text (the rest fall back to the start of their page)."""
    count = len(pages)
    per_page = [[ln for ln in (" ".join(raw.split()) for raw in text.splitlines()) if ln] for text in pages]
    seen: Counter[str] = Counter()
    for lines in per_page:
        seen.update({furniture_key(ln) for ln in lines})
    limit = max(3, count // 4)
    cleaned = ["\n".join(ln for ln in lines if seen[furniture_key(ln)] < limit) for lines in per_page]
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
