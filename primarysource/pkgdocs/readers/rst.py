"""A minimal reStructuredText reader for PEPs, Debian Policy, GLEPs and the kernel's Kconfig documents.

Sections follow the docutils rule: a title is a text line with an underline (or an underline and an overline of
the same character) at least as long as the title, and the level of a style is the order in which the style first
appears in the document, not the character used. A document whose first heading is the only one of its style
(a chapter title above its sections) has that heading promoted to the document title; with `base` it opens the
numbered root section, so chapter 5's subsections are `5.1`, `5.1.1`.

Blocks (the unit, so `¶n` counts blocks):

- a paragraph; a block quote; a literal block (the indented text after a paragraph ending in `::`);
- a list item (`-`, `*`, `+`, `1.`, `#.`, `(a)`) or a field (`:name: value`) with its indented continuation;
- a definition-list item (a term and its indented definition);
- a directive (`.. name:: args` and its indented body) as one block, written `[name] args` then the body;
- a footnote or citation (`.. [#]`), written `[footnote]`; a grid or simple table.

Comments (`.. text`), substitution definitions (`.. |x| ...`), hyperlink targets and transitions are dropped. A
target `.. _label:` immediately before a heading becomes that section's anchor, the way Sphinx labels are used;
otherwise the anchor is the GitHub-style slug of the title.

Nothing here follows `.. include::`, `.. literalinclude::` or `.. raw::`: they are inert text, and no path a
document names is ever opened. There is no recursion, so deep indentation costs time linear in the input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import Builder, clean_title, decode, slugify

_PUNCT = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_MARKER = re.compile(r"(?:[-*+•‣⁃](?:\s+\S|$)|(?:\d+|[a-zA-Z]|#)[.)]\s+\S|\((?:\d+|[a-zA-Z]|#)\)\s+\S)")
_FIELD = re.compile(r":[^\s:][^:]*:(?:\s|$)")
_DIRECTIVE = re.compile(r"\.\. +([A-Za-z][\w:+.-]*)::(?: +(.*))?$")
_TARGET = re.compile(r"\.\. +_(`[^`]+`|[^:`]+):(?: +(.*))?$")
_FOOTNOTE = re.compile(r"\.\. +\[([^\]]*)\](?: +(.*))?$")
_SUBST = re.compile(r"\.\. +\|[^|]+\|")
_SIMPLE_BORDER = re.compile(r"=+(?: +=+)+$")


@dataclass(frozen=True, slots=True)
class _Heading:
    style: str
    title: str
    anchor: str


def _adornment(line: str) -> str | None:
    """The style character if `line` is one punctuation character repeated at least twice, else None."""
    if len(line) >= 2 and line[0] in _PUNCT and line.count(line[0]) == len(line):
        return line[0]
    return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _dedent(lines: list[str]) -> str:
    live = [line for line in lines if line.strip()]
    if not live:
        return ""
    margin = min(_indent(line) for line in live)
    return "\n".join(line[margin:] if line.strip() else "" for line in lines).strip("\n")


def _take_indented(lines: list[str], i: int) -> tuple[list[str], int]:
    """Lines from `i` that are indented, plus blank lines that are followed by more indented lines."""
    body: list[str] = []
    count = len(lines)
    while i < count:
        line = lines[i]
        if line.strip() and _indent(line) > 0:
            body.append(line)
            i += 1
            continue
        if not line.strip():
            j = i
            while j < count and not lines[j].strip():
                j += 1
            if j < count and _indent(lines[j]) > 0:
                body.extend([""] * (j - i))
                i = j
                continue
        break
    return body, i


def _parse(lines: list[str]) -> list[_Heading | str]:
    events: list[_Heading | str] = []
    pending_label = ""
    count = len(lines)
    i = 0
    while i < count:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _indent(line) > 0:  # a block quote
            body, i = _take_indented(lines, i)
            events.append(_dedent(body))
            pending_label = ""
            continue
        # headings: text over an underline, or an overlined title
        style = _adornment(line)
        if style and i + 2 < count and lines[i + 1].strip() and lines[i + 2].rstrip() == line:
            title = lines[i + 1].strip()
            if _indent(lines[i + 1]) == 0 and _adornment(lines[i + 1]) is None and len(line) >= len(title):
                events.append(_Heading(style + "o", title, pending_label or slugify(title)))
                pending_label = ""
                i += 3
                continue
        if style is None and i + 1 < count and not line.startswith(".."):
            under = _adornment(lines[i + 1])
            if under and len(lines[i + 1]) >= len(line.strip()) and _MARKER.match(line) is None:
                title = line.strip()
                events.append(_Heading(under, title, pending_label or slugify(title)))
                pending_label = ""
                i += 2
                continue
        if style and len(line) >= 4 and (i + 1 >= count or not lines[i + 1].strip()):
            i += 1  # a transition
            continue
        if line.startswith(".."):
            i, pending_label = _explicit(lines, i, events, pending_label)
            continue
        if line.startswith(("+-", "+=")):  # a grid table
            start = i
            while i < count and lines[i].strip():
                i += 1
            events.append("\n".join(lines[start:i]))
            pending_label = ""
            continue
        if _SIMPLE_BORDER.match(line):
            start, borders = i, 0
            while i < count:
                if _SIMPLE_BORDER.match(lines[i]):
                    borders += 1
                if not lines[i].strip() and borders >= 2:
                    break
                i += 1
            events.append("\n".join(lines[start:i]).rstrip())
            pending_label = ""
            continue
        # a paragraph, list item, field or definition item
        start = i
        first = _MARKER.match(line) is not None or _FIELD.match(line) is not None
        i += 1
        if not first:
            while i < count and lines[i].strip() and _indent(lines[i]) == 0:
                if _MARKER.match(lines[i]) or _FIELD.match(lines[i]):
                    break
                i += 1
        text_lines = lines[start:i]
        if i < count and lines[i].strip() and _indent(lines[i]) > 0:  # a definition or a list continuation
            body, i = _take_indented(lines, i)
            text_lines = [*text_lines, *body]
            events.append(_dedent(text_lines) if first else "\n".join(text_lines).strip("\n"))
        elif text_lines[-1].rstrip().endswith("::"):
            paragraph = "\n".join(text_lines)
            if paragraph.strip() != "::":
                events.append(paragraph)
            body, i = _take_indented(lines, _skip_blank(lines, i))
            if body:
                events.append(_dedent(body))
        else:
            events.append("\n".join(text_lines))
        pending_label = ""
    return events


def _skip_blank(lines: list[str], i: int) -> int:
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i


def _explicit(lines: list[str], i: int, events: list[_Heading | str], label: str) -> tuple[int, str]:
    """An explicit markup block (`.. ...`): returns the next index and the label still pending."""
    head = lines[i]
    body, nxt = _take_indented(lines, i + 1)
    target = _TARGET.match(head)
    if target:
        name = target.group(1).strip("`")
        if not (target.group(2) or "").strip() and not body:
            return nxt, name
        return nxt, label
    directive = _DIRECTIVE.match(head)
    if directive:
        text = f"[{directive.group(1)}]" + (f" {directive.group(2).strip()}" if directive.group(2) else "")
        if body:
            text += "\n" + _dedent(body)
        events.append(text)
        return nxt, ""
    footnote = _FOOTNOTE.match(head)
    if footnote:
        first = (footnote.group(2) or "").strip()
        text = f"[footnote {footnote.group(1)}] " + first
        if body:
            text += "\n" + _dedent(body)
        events.append(text.rstrip())
        return nxt, ""
    if _SUBST.match(head):
        return nxt, label
    return nxt, label  # a comment: dropped


def read_rst(data: bytes, doc_id: str, title: str | None = None, *, base: str = "") -> Doc:
    """Read one reStructuredText file. Raises `LibError` for NUL bytes or invalid UTF-8; everything else reads."""
    text = decode(data, f"reStructuredText file {doc_id!r}")
    lines = [line.rstrip() for line in text.expandtabs(8).split("\n")]
    events = _parse(lines)
    headings = [e for e in events if isinstance(e, _Heading)]
    promote = bool(headings) and events[0] is headings[0] and sum(h.style == headings[0].style for h in headings) == 1
    order: list[str] = []
    for heading in headings[1 if promote else 0 :]:
        if heading.style not in order:
            order.append(heading.style)
    builder = Builder(base)
    doc_title = title or ""
    rest = events
    if promote:
        first = headings[0]
        doc_title = title or clean_title(first.title)
        builder.root(first.title, first.anchor)
        rest = events[1:]
    else:
        builder.set_preamble_title(doc_title or doc_id)
        if base:
            builder.root(doc_title or doc_id)
    for event in rest:
        if isinstance(event, _Heading):
            builder.heading(order.index(event.style) + 1, event.title, event.anchor)
        else:
            builder.unit(event)
    return builder.doc(doc_id, doc_title or doc_id, unit=Unit.BLOCK)
