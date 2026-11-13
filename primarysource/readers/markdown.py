"""A small, strict Markdown reader: headings, blocks, front matter. The core's `cl.reader_markdown`.

Written for the C2SP specifications (`primarysource/c2sp/markdown.py`, now a re-export of this module). It reads
the subset those specifications use and nothing else is interpreted: ATX headings (`#` to `######`),
setext headings over one paragraph line, fenced code (backticks or tildes), blank-line-separated blocks, and a
leading `---` front-matter block of `key: value` lines. HTML, links and images are never followed or rendered;
a heading's title is its text with link targets, emphasis marks and code ticks removed.

Input is bounded (`MAX_BYTES`, `MAX_LINE`, `MAX_SECTIONS`) because the text of a specification is untrusted data:
a document over a bound is refused with a `LibError`, never truncated.

Units: `¶n` counts blocks. A block is a blank-line-separated chunk of lines, or one whole fenced code block
(blank lines inside a fence do not split it). A section's units are every block from its heading to the next
heading of the same or a higher level, subsection headings included as blocks, its own heading excluded.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from primarysource.errors import LibError

MAX_BYTES = 4 * 1024 * 1024
MAX_LINE = 20_000
MAX_SECTIONS = 20_000

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_REFLINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_TAG = re.compile(r"<[^>\n]*>")
_MARKS = re.compile(r"[`*_~]+")
_SLUG_DROP = re.compile(r"[^\w\- ]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Heading:
    """One section of a document, in document order. `units` are its blocks (see the module docstring)."""

    title: str
    slug: str
    level: int
    units: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    """What the reader found. `preamble` is the blocks before the first heading; `title` is the first level-1
    heading, else the front matter's `title`, else empty."""

    front: dict[str, str]
    title: str
    preamble: tuple[str, ...]
    headings: tuple[Heading, ...]

    def units(self) -> tuple[str, ...]:
        """The whole document as units: the preamble, then every block of every top-level section, with each
        heading as a block of its own."""
        if not self.headings:
            return self.preamble
        top = min(h.level for h in self.headings)
        out = list(self.preamble)
        for heading in self.headings:
            if heading.level == top:
                out.append(f"{'#' * heading.level} {heading.title}")
                out.extend(heading.units)
        return tuple(out)


def plain(text: str) -> str:
    """A heading's text without Markdown: links reduced to their text, tags, ticks and emphasis marks removed."""
    text = _LINK.sub(r"\1", text)
    text = _REFLINK.sub(r"\1", text)
    text = _TAG.sub("", text)
    text = _MARKS.sub("", text)
    return " ".join(text.split())


def slugify(title: str) -> str:
    """The GitHub-style anchor of a title: lower case, punctuation dropped, spaces to hyphens."""
    folded = unicodedata.normalize("NFKC", title).lower()
    return _SLUG_DROP.sub("", folded).strip().replace(" ", "-")


def _front_matter(lines: list[str]) -> tuple[dict[str, str], int]:
    """Parse a leading `---` block of `key: value` lines; return it and the index of the first body line."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    for end in range(1, min(len(lines), 60)):
        if lines[end].strip() == "---":
            front: dict[str, str] = {}
            for line in lines[1:end]:
                key, sep, value = line.partition(":")
                if sep and re.fullmatch(r"[A-Za-z][\w-]*", key.strip()):
                    front[key.strip()] = value.strip().strip("\"'")
            return front, end + 1
    return {}, 0


def decode(data: bytes) -> str:
    """UTF-8 text from bytes, or a `LibError`: over the bound, not UTF-8, or containing a NUL."""
    if len(data) > MAX_BYTES:
        raise LibError(f"document is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LibError("document is not valid UTF-8", "re-import it; the pinned file is UTF-8") from exc
    if "\x00" in text:
        raise LibError("document contains a NUL byte", "re-import it; the pinned file is plain text")
    return text


def parse(data: bytes | str) -> MarkdownDocument:
    """Parse one document. Raises `LibError` for a document that is not UTF-8 text or exceeds a bound."""
    text = decode(data) if isinstance(data, bytes) else data
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if any(len(line) > MAX_LINE for line in lines):
        raise LibError(f"document has a line over {MAX_LINE} characters", "")
    front, first = _front_matter(lines)

    # pass 1: split into (kind, level, text) items: headings and blocks, fences kept whole
    items: list[tuple[str, int, str]] = []
    paragraph: list[str] = []
    fence: tuple[str, int] | None = None
    fenced: list[str] = []

    def flush() -> None:
        if paragraph:
            items.append(("block", 0, "\n".join(paragraph)))
            paragraph.clear()

    for line in lines[first:]:
        if fence is not None:
            fenced.append(line)
            close = _FENCE.match(line)
            if close and close.group(1)[0] == fence[0] and len(close.group(1)) >= fence[1] and not line.strip(" `~"):
                items.append(("block", 0, "\n".join(fenced)))
                fence, fenced = None, []
            continue
        opening = _FENCE.match(line)
        if opening:
            flush()
            fence, fenced = (opening.group(1)[0], len(opening.group(1))), [line]
            continue
        if not line.strip():
            flush()
            continue
        atx = _ATX.match(line)
        if atx:
            flush()
            items.append(("heading", len(atx.group(1)), plain(atx.group(2) or "")))
            continue
        setext = _SETEXT.match(line)
        if setext and len(paragraph) == 1 and not paragraph[0].lstrip().startswith(("-", "*", ">", "|")):
            items.append(("heading", 1 if setext.group(1)[0] == "=" else 2, plain(paragraph[0])))
            paragraph.clear()
            continue
        paragraph.append(line)
    if fence is not None:  # an unclosed fence runs to the end of the document, as in CommonMark
        items.append(("block", 0, "\n".join(fenced)))
    flush()

    # pass 2: assign blocks to sections
    spans = [(body, level, index) for index, (kind, level, body) in enumerate(items) if kind == "heading"]
    if len(spans) > MAX_SECTIONS:
        raise LibError(f"document has {len(spans)} headings, over the {MAX_SECTIONS} bound", "")
    first_heading = spans[0][2] if spans else len(items)
    preamble = tuple(body for kind, _, body in items[:first_heading] if kind == "block")
    headings: list[Heading] = []
    seen: dict[str, int] = {}
    for n, (title, level, start) in enumerate(spans):
        end = len(items)
        for _, later_level, later in spans[n + 1 :]:
            if later_level <= level:
                end = later
                break
        units = tuple(
            f"{'#' * item_level} {body}".rstrip() if kind == "heading" else body
            for kind, item_level, body in items[start + 1 : end]
        )
        slug = slugify(title)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        headings.append(Heading(title, slug if count == 0 else f"{slug}-{count}", level, units))
    top = next((h.title for h in headings if h.level == 1), "")
    return MarkdownDocument(front, top or front.get("title", ""), preamble, tuple(headings))
