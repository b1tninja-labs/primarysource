"""Cut a Word RTF paper into outline sections of sentences.

The Windows Imaging File Format paper is published as RTF, not as an Open Specifications PDF. This reader
takes those bytes and never writes them. A paragraph marked `\\outlinelevel` is a heading; the text until the
next heading is that section. Groups that are not body text (the stylesheet, fonts, pictures, field
instructions) are skipped. No third-party RTF library.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from primarysource.errors import LibError
from primarysource.readers.bookmarks import heading_id, split_sentences

MAX_BYTES = 8 * 1024 * 1024
_SKIP = frozenset(
    {
        "annotation",
        "author",
        "bkmkend",
        "bkmkstart",
        "colortbl",
        "colorschememapping",
        "comment",
        "company",
        "datafield",
        "datastore",
        "doccomm",
        "filetbl",
        "fldinst",
        "fonttbl",
        "footer",
        "footerf",
        "footerl",
        "footerr",
        "footnote",
        "header",
        "headerf",
        "headerl",
        "headerr",
        "info",
        "keywords",
        "latentstyles",
        "listoverridetable",
        "listtable",
        "nonshppict",
        "object",
        "operator",
        "pict",
        "pntext",
        "private",
        "revtbl",
        "rsidtbl",
        "shp",
        "shpinst",
        "shppict",
        "stylesheet",
        "themedata",
        "title",
        "xmlnstbl",
    }
)
_HEX = re.compile(r"[0-9A-Fa-f]{2}")


def extract(data: bytes) -> dict[str, Any]:
    """`{"title", "pages", "extractor", "headings_found", "segmenter", "sections"}` for `data`.

    `sections` matches the PDF extraction shape (`id`, `title`, `depth`, `page`, `text`) so the same index
    can store it. A file over `MAX_BYTES`, or one with no outline heading, is a `LibError`."""
    if len(data) > MAX_BYTES:
        raise LibError(f"the RTF is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    if not data.startswith(b"{\\rtf"):
        raise LibError("the file is not an RTF document", "the Windows Imaging paper is an RTF download")
    paragraphs = _paragraphs(data.decode("latin-1"))
    sections = _sections(paragraphs)
    if not any(section["id"] != "front-matter" for section in sections):
        raise LibError(
            "the RTF has no outline headings to split it into sections",
            "this reader needs paragraphs marked with an outline level",
        )
    pages = max(section["page"] for section in sections)
    title = next((section["title"] for section in sections if section["id"] != "front-matter"), "")
    return {
        "title": title,
        "pages": pages,
        "extractor": "rtf",
        "headings_found": sum(1 for section in sections if section["id"] != "front-matter"),
        "segmenter": "outline",
        "sections": sections,
    }


def _sections(paragraphs: list[tuple[int | None, int, str]]) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for level, page, text in paragraphs:
        if level is None:
            if current is None:
                current = {"id": "front-matter", "title": "Front matter", "depth": 0, "page": page, "parts": []}
                built.append(current)
            current["parts"].append(text)
            continue
        ident, title = heading_id(text)
        current = {"id": ident, "title": title, "depth": level, "page": page, "parts": []}
        built.append(current)
    used: Counter[str] = Counter()
    sections: list[dict[str, Any]] = []
    for section in built:
        ident = str(section["id"])
        used[ident] += 1
        if used[ident] > 1:
            ident = f"{ident}-{used[ident] - 1}"
        sections.append(
            {
                "id": ident,
                "title": section["title"],
                "depth": section["depth"],
                "page": section["page"],
                "text": "\n".join(split_sentences(" ".join(section["parts"]))),
            }
        )
    return sections


def _paragraphs(text: str) -> list[tuple[int | None, int, str]]:
    """`(outline level or None, 1-based page, paragraph text)` for body paragraphs."""
    paragraphs: list[tuple[int | None, int, str]] = []
    skip: list[bool] = []
    parts: list[str] = []
    outline: int | None = None
    page = 1
    uc = 1
    i = 0
    n = len(text)

    def skipped() -> bool:
        return bool(skip) and skip[-1]

    def flush() -> None:
        nonlocal outline
        cleaned = " ".join("".join(parts).split())
        parts.clear()
        level, outline = outline, None
        if cleaned:
            paragraphs.append((level, page, cleaned))

    while i < n:
        char = text[i]
        if char in "\r\n":
            i += 1
            continue
        if char == "{":
            skip.append(skipped() or _destination(text, i + 1))
            i += 1
            continue
        if char == "}":
            if skip:
                skip.pop()
            i += 1
            continue
        if char != "\\":
            if not skipped():
                parts.append(char)
            i += 1
            continue
        word, arg, i = _control(text, i + 1)
        if skipped():
            if word == "bin" and arg:
                i = min(n, i + arg)
            continue
        if word in {"par", "row"}:
            flush()
        elif word == "pard":
            if parts:
                flush()
            outline = None
        elif word == "outlinelevel" and arg is not None:
            outline = arg
        elif word == "page":
            page += 1
        elif word == "uc" and arg is not None:
            uc = arg
        elif word == "u" and arg is not None:
            code = arg + 65536 if arg < 0 else arg
            parts.append(chr(code))
            i = _skip_fallback(text, i, uc)
        elif word == "'" and arg is not None:
            parts.append(chr(arg))
        elif word in {"\\", "{", "}"}:
            parts.append(word)
        elif word in {"tab", "line", "cell", "emdash", "endash", "~", "_"}:
            parts.append(" ")
        elif word == "bin" and arg:
            i = min(n, i + arg)
    if parts:
        flush()
    return paragraphs


def _destination(text: str, i: int) -> bool:
    """True when the group that starts at `i - 1` is not body text."""
    n = len(text)
    while i < n and text[i] in " \r\n":
        i += 1
    if i >= n or text[i] != "\\":
        return False
    i += 1
    if i < n and text[i] == "*":
        return True
    end = i
    while end < n and text[end].isalpha():
        end += 1
    return text[i:end] in _SKIP


def _control(text: str, i: int) -> tuple[str, int | None, int]:
    """The control at `i` (just after the backslash): its name, its argument, and the index after it."""
    n = len(text)
    if i >= n:
        return "", None, i
    char = text[i]
    if char in "\\{}":
        return char, None, i + 1
    if char == "'":
        digits = text[i + 1 : i + 3]
        if _HEX.fullmatch(digits):
            return "'", int(digits, 16), i + 3
        return "'", None, i + 1
    if char == "*":
        return "*", None, i + 1
    end = i
    while end < n and text[end].isalpha():
        end += 1
    word = text[i:end]
    i = end
    sign = 1
    if i < n and text[i] == "-":
        sign = -1
        i += 1
    end = i
    while end < n and text[end].isdigit():
        end += 1
    arg = sign * int(text[i:end]) if end > i else None
    i = end
    if i < n and text[i] == " ":
        i += 1
    return word, arg, i


def _skip_fallback(text: str, i: int, count: int) -> int:
    """Skip `count` fallback characters after a `\\u` (a literal, or one hex escape)."""
    n = len(text)
    left = count
    while left > 0 and i < n:
        if text[i] in "\r\n":
            i += 1
            continue
        if text[i] == "\\" and i + 3 < n and text[i + 1] == "'" and _HEX.fullmatch(text[i + 2 : i + 4]):
            i += 4
        else:
            i += 1
        left -= 1
    return i
