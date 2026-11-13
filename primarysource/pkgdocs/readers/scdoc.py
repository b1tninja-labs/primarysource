"""A minimal scdoc reader for rpm's manual pages (`docs/man/*.scd`).

scdoc is the small man-page markup rpm uses in place of roff. The first line is `NAME(section)` (optionally with
quoted footer strings); `#`, `##` and `###` start sections; `;` at the start of a line is a comment.

Blocks (the unit): a paragraph, a list item (`- ` or `. ` with its indented continuation and nested items), a
literal block (a fenced ``` block, or lines indented by a tab or four spaces) and a table (`[[` to the blank
line). Inline markup (`*bold*`, `_underline_`, `\\` escapes) is left as written.

The document title is the header line, lower-cased: `rpm-macros(7)`. The collection adds the NAME description.
"""

from __future__ import annotations

import re

from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import Builder, decode

_HEADER = re.compile(r"([A-Za-z0-9_.+-]+)\((\d)\)(?:\s+\"[^\"]*\"){0,2}")
_ITEM = re.compile(r"(?:-|\.)\s+\S")
_HEADING = re.compile(r"(#{1,3})\s+(\S.*)")


def read_scdoc(data: bytes, doc_id: str, title: str | None = None) -> Doc:
    """Read one scdoc file. Raises `LibError` for NUL bytes or invalid UTF-8; everything else reads."""
    text = decode(data, f"scdoc file {doc_id!r}")
    lines = [ln.rstrip() for ln in text.expandtabs(4).split("\n")]
    count = len(lines)
    i = 0
    doc_title = title or ""
    while i < count and (not lines[i].strip() or lines[i].startswith(";")):
        i += 1
    header = _HEADER.fullmatch(lines[i].strip()) if i < count else None
    if header:
        doc_title = doc_title or f"{header.group(1).lower()}({header.group(2)})"
        i += 1
    builder = Builder()
    builder.set_preamble_title(doc_title or doc_id)
    para: list[str] = []

    def flush() -> None:
        if para:
            builder.unit("\n".join(para))
            para.clear()

    while i < count:
        line = lines[i]
        i += 1
        if line.startswith(";"):
            continue
        if not line.strip():
            flush()
            continue
        if line.startswith("```"):
            flush()
            block = [line]
            while i < count:
                block.append(lines[i])
                i += 1
                if block[-1].startswith("```"):
                    break
            builder.unit("\n".join(block))
            continue
        heading = _HEADING.fullmatch(line)
        if heading:
            flush()
            builder.heading(len(heading.group(1)), heading.group(2))
            continue
        if line.startswith("[["):
            flush()
            block = [line]
            while i < count and lines[i].strip():
                block.append(lines[i])
                i += 1
            builder.unit("\n".join(block))
            continue
        if line.startswith("    ") and not para:
            block = [line]
            while i < count and (lines[i].startswith("    ") or not lines[i].strip()):
                block.append(lines[i])
                i += 1
            builder.unit("\n".join(block).rstrip())
            continue
        if _ITEM.match(line):
            flush()
            item = [line]
            while i < count:
                nxt = lines[i]
                if nxt.strip() and (nxt.startswith("  ") or not _ITEM.match(nxt) and not _HEADING.fullmatch(nxt)):
                    item.append(nxt)
                    i += 1
                    continue
                if not nxt.strip():
                    j = i
                    while j < count and not lines[j].strip():
                        j += 1
                    if j < count and lines[j].startswith("  "):
                        item.extend([""] * (j - i))
                        i = j
                        continue
                break
            builder.unit("\n".join(item))
            continue
        para.append(line)
    flush()
    return builder.doc(doc_id, doc_title or doc_id, unit=Unit.BLOCK)
