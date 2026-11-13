"""Draft text -> sections and paragraph blocks, by the `rfc` collection's `.txt` segmenter.

A draft's `.txt` is the same xml2rfc rendering as an RFC's, so `primarysource.rfc.index.txtseg` (table of
contents as the answer key, headings found in order, paragraphs re-joined across page breaks) reads it
unchanged; the one thing a draft adds is its own page furniture, which that segmenter already skips by its
`[Page N]` footer. The author's `.xml` is not segmented: it is the *submitted* source, not the prepared one, so
it has no `pn` ids and no section numbers, which is what `rfc.index.rfcxml` needs. See `docs/draft.md`.

What is added here:

- the text is normalised first (CRLF and lone CR to LF, form feeds and the other `str.splitlines` separators
  removed) so line N of the segmentation is line N of the file, and refs like `draft-x-y-03:100-120` mean what
  they say;
- hostile text is refused before the segmenter sees it (NUL, over-long lines, over-size files), because its
  regular expressions are written for well-formed RFC text;
- section ids are the ones a ref can carry: `5.1`, `A.2` for an appendix, a title slug for an unnumbered
  section (`abstract`, `security-considerations`), made unique with `-2`, `-3`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from primarysource.errors import LibError
from primarysource.rfc.index import txtseg

PARSER_VERSION = "2"
MAX_TEXT_BYTES = 8_000_000
MAX_LINE = 2_000
MAX_LINES = 60_000

_SEPARATORS = str.maketrans({c: " " for c in "\x0b\x1c\x1d\x1e\x85  "} | {"\f": None})
_SLUG = re.compile(r"[^a-z0-9]+")
# The running header of a draft's pages: "Internet-Draft    Short Title    November 2026". The rfc segmenter skips
# the same line in an RFC ("RFC 9000    QUIC    May 2021") and re-joins the paragraph the page break cut, so the
# header is rewritten to that spelling, column for column, rather than blanked (which would split the paragraph).
_PAGE_HEADER = re.compile(r"^Internet-Draft( {2,}.*\S {2,}\S+ \d{4}\s*)$")


@dataclass(frozen=True, slots=True)
class Block:
    """One paragraph, list, figure or table of a section, with its 1-based line range in the normalised text."""

    text: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class DSection:
    """`id` is what a ref's `§` carries; `num` is the number the draft prints (`5.1`, `Appendix A`, or '')."""

    id: str
    num: str
    title: str
    depth: int
    head_line: int
    end_line: int
    blocks: tuple[Block, ...]


@dataclass(frozen=True, slots=True)
class Segmented:
    sections: tuple[DSection, ...]
    lines: int
    method: str
    notes: tuple[str, ...]

    def section(self, section_id: str) -> DSection | None:
        for candidate in self.sections:
            if candidate.id == section_id:
                return candidate
        return None

    def to_json(self) -> str:
        return json.dumps(
            {
                "parser": PARSER_VERSION,
                "lines": self.lines,
                "method": self.method,
                "notes": list(self.notes),
                "sections": [
                    {
                        "id": s.id,
                        "num": s.num,
                        "title": s.title,
                        "depth": s.depth,
                        "head": s.head_line,
                        "end": s.end_line,
                        "blocks": [[b.text, b.kind, b.start, b.end] for b in s.blocks],
                    }
                    for s in self.sections
                ],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(text: str) -> Segmented | None:
        """The cached segmentation, or None when it is damaged or was made by another parser version (the caller
        then segments the stored text again)."""
        try:
            raw: dict[str, Any] = json.loads(text)
            if raw["parser"] != PARSER_VERSION:
                return None
            sections = tuple(
                DSection(
                    str(s["id"]),
                    str(s["num"]),
                    str(s["title"]),
                    int(s["depth"]),
                    int(s["head"]),
                    int(s["end"]),
                    tuple(Block(str(b[0]), str(b[1]), int(b[2]), int(b[3])) for b in s["blocks"]),
                )
                for s in raw["sections"]
            )
            return Segmented(sections, int(raw["lines"]), str(raw["method"]), tuple(str(n) for n in raw["notes"]))
        except (ValueError, KeyError, TypeError, IndexError):
            return None


def decode(data: bytes) -> tuple[str, str]:
    """Bytes of a draft's `.txt` -> (text, encoding). UTF-8 if it is, else Latin-1, which the oldest drafts are;
    a NUL byte means this is not a text draft at all."""
    if len(data) > MAX_TEXT_BYTES:
        raise LibError(f"a draft text of {len(data):,} bytes is over the {MAX_TEXT_BYTES:,} byte limit", "")
    if b"\x00" in data:
        raise LibError("the file holds NUL bytes: this is not a text draft", "")
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def normalise(text: str) -> list[str]:
    """Lines of `text` such that line N is the Nth newline-separated line of the file, with the BOM, form feeds and
    odd separators gone. Raises a LibError for a line or a file the segmenter should not be handed."""
    flat = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").translate(_SEPARATORS)
    lines = flat.split("\n")
    if len(lines) > MAX_LINES:
        raise LibError(f"{len(lines):,} lines is over the {MAX_LINES:,} line limit for a draft", "")
    longest = max((len(line) for line in lines), default=0)
    if longest > MAX_LINE:
        raise LibError(
            f"a line of {longest:,} characters is over the {MAX_LINE:,} limit: this is not a text draft", ""
        )
    return [_PAGE_HEADER.sub(lambda m: "RFC 0" + " " * 9 + m.group(1), line) for line in lines]


def section_id(num: str, title: str, used: set[str]) -> str:
    """A ref-safe, unique id for a section."""
    if num.startswith("Appendix "):
        base = num.split(" ", 1)[1]
    elif num:
        base = num
    else:
        base = _SLUG.sub("-", title.lower()).strip("-")[:60] or "section"
    found, n = base, 2
    while found in used:
        found, n = f"{base}-{n}", n + 1
    used.add(found)
    return found


def segment(text: str) -> Segmented:
    """Sections and blocks of a draft's text. Never returns nothing: a draft with no headings is one section."""
    lines = normalise(text)
    parsed, quality = txtseg.segment("\n".join(lines), "draft")
    shift = 0
    if any("no headings" in note for note in quality.notes):
        # the rfc segmenter treats line 1 as the heading of its single "Entire document" section and drops it;
        # one blank line in front gives that role to nothing, and every line number is then one too high
        parsed, quality = txtseg.segment("\n" + "\n".join(lines), "draft")
        shift = 1
    used: set[str] = set()
    sections: list[DSection] = []
    for s in parsed.sections:
        blocks = tuple(
            Block(b.text, b.kind, b.start_line - shift, b.end_line - shift) for b in s.blocks if b.text.strip()
        )
        sections.append(
            DSection(
                section_id(s.sec_num, s.title, used), s.sec_num, s.title, s.depth,
                max(1, s.head_line - shift), max(1, s.end_line - shift), blocks,
            )
        )  # fmt: skip
    return Segmented(tuple(sections), len(lines), quality.method, tuple(quality.notes))
