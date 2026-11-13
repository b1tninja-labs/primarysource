"""A minimal Markdown reader for rpm's manual and Debian's autopkgtest specification.

Headings are ATX (`#` to `######`) or setext (`===` / `---` under a paragraph). Section ids are the ordinal path
(`2`, `2.1`); the anchor is the GitHub-style slug of the title, duplicates suffixed `-1`, `-2`. That slug is the
rule used here; this module does not claim CommonMark defines it. Text before the first heading is section `0`,
titled with the document title. YAML front matter (a first line `---`) is not a section; its `title:` is used
when no title is given.

Blocks (the unit): a paragraph (a run of non-blank lines), a fenced code block as one block with its fences, an
indented code block, a block quote, a table, and each **top-level** list item with everything nested inside it.
HTML comments are dropped (a `<!-- -->` hiding a `#` line hides it from the outline too); an unclosed fence or
comment runs to the end of the file, so no text is lost to a typo. Inline markup is left as written.
"""

from __future__ import annotations

import re

from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import Builder, decode

_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_ITEM = re.compile(r" {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]+\S|[ \t]*$)")
_RULE = re.compile(r" {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_SETEXT = re.compile(r" {0,3}(=+|-+)[ \t]*$")
_TABLE_SEP = re.compile(r"[ \t|:-]+$")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _atx(line: str) -> tuple[int, str] | None:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3 or not stripped.startswith("#"):
        return None
    body = stripped.lstrip("#")
    level = len(stripped) - len(body)
    if level > 6 or (body and body[0] not in " \t"):
        return None
    title = body.strip()
    if title.endswith("#"):
        shorter = title.rstrip("#")
        if not shorter or shorter[-1] in " \t":
            title = shorter.strip()
    return level, title


def _front_matter(lines: list[str]) -> tuple[int, str]:
    """(first line after the front matter, its `title:`), or (0, "") when there is none."""
    if not lines or lines[0].strip() != "---":
        return 0, ""
    for end in range(1, min(len(lines), 200)):
        if lines[end].strip() in ("---", "..."):
            title = ""
            for line in lines[1:end]:
                key, _, value = line.partition(":")
                if key.strip() == "title" and value.strip():
                    title = value.strip().strip("\"'")
            return end + 1, title
    return 0, ""


def read_markdown(data: bytes, doc_id: str, title: str | None = None) -> Doc:
    """Read one Markdown file. Raises `LibError` for NUL bytes or invalid UTF-8; everything else reads."""
    text = decode(data, f"Markdown file {doc_id!r}")
    lines = [ln.rstrip() for ln in text.expandtabs(4).split("\n")]
    i, fm_title = _front_matter(lines)
    doc_title = title or fm_title
    builder = Builder()
    first_h1 = ""
    count = len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            builder.unit("\n".join(para))
            para.clear()

    def heading(level: int, name: str) -> None:
        nonlocal first_h1
        name = _LINK.sub(chr(92) + "1", name)
        first_h1 = first_h1 or (name if level == 1 else "")
        builder.heading(level, name)

    while i < count:
        line = lines[i]
        i += 1
        if not line.strip():
            flush()
            continue
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker = fence.group(1)
            block = [line]
            while i < count:
                closing = lines[i].strip()
                block.append(lines[i])
                i += 1
                if closing.startswith(marker[0] * len(marker)) and closing.strip(marker[0]) == "":
                    break
            builder.unit("\n".join(block).rstrip("\n"))
            continue
        if line.lstrip().startswith("<!--"):
            flush()
            i -= 1
            while i < count and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        atx = _atx(line)
        if atx:
            flush()
            if atx[1]:
                heading(*atx)
            continue
        setext = _SETEXT.match(line)
        if setext and para:
            name = " ".join(para)
            para.clear()
            heading(1 if setext.group(1)[0] == "=" else 2, name)
            continue
        if _RULE.match(line) and not para:
            continue
        if para:
            starts = _ITEM.match(line) or line.lstrip().startswith(">") or "|" in line
            if not starts:
                para.append(line)
                continue
            flush()
        if _ITEM.match(line):
            item = [line]
            while i < count:
                nxt = lines[i]
                if not nxt.strip():
                    j = i
                    while j < count and not lines[j].strip():
                        j += 1
                    if j < count and (len(lines[j]) - len(lines[j].lstrip(" "))) >= 2:
                        item.extend([""] * (j - i))
                        i = j
                        continue
                    break
                indented = (len(nxt) - len(nxt.lstrip(" "))) >= 2
                if not indented and (_ITEM.match(nxt) or _atx(nxt) or _FENCE.match(nxt) or _RULE.match(nxt)):
                    break
                item.append(nxt)
                i += 1
            builder.unit("\n".join(item))
            continue
        if line.lstrip().startswith(">"):
            block = [line]
            while i < count and lines[i].strip() and (lines[i].lstrip().startswith(">") or not _atx(lines[i])):
                block.append(lines[i])
                i += 1
            builder.unit("\n".join(block))
            continue
        if "|" in line and i < count and _TABLE_SEP.match(lines[i]) and "-" in lines[i] and "|" in lines[i]:
            block = [line]
            while i < count and lines[i].strip() and "|" in lines[i]:
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
        para.append(line)
    flush()
    return builder.doc(doc_id, doc_title or first_h1 or doc_id, unit=Unit.BLOCK)
