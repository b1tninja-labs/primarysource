"""One ref grammar, parameterised by what a document id looks like.

The three libraries that have a ref string agree on its shape and differ only in the document id:

    RFC9000§9.6¶2      X.690§11.6¶2      devdocs_en_flask§blueprints/index#why¶3

So the grammar is `<doc> § <section> [#anchor] [¶ n]`, or `<doc> : first-last` for a line range. `::` is the
ASCII spelling of `§`. A library supplies the pattern for its document ids and, if its sections are not dotted
numbers, the pattern for those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from primarysource.errors import LibError

DOTTED_SECTION = r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*"


@dataclass(frozen=True, slots=True)
class Ref:
    """A parsed ref. Every part but one may be None; `lines` is (first, last), 1-based and inclusive."""

    doc: str | None = None
    section: str | None = None
    para: int | None = None
    anchor: str | None = None
    lines: tuple[int, int] | None = None


class RefParser(Protocol):
    """What a collection's refs need: text to `Ref` and back. `RefGrammar` is one; a collection whose refs are not
    `<doc>§<section>` (an id-keyed registry such as `usbids:1d6b:0002`) supplies its own object with these two
    methods, raising `LibError` for text that is not a ref."""

    def parse(self, text: str) -> Ref: ...

    def format(self, ref: Ref) -> str: ...


class RefGrammar:
    """Parses and formats refs for one library."""

    def __init__(self, doc_pattern: str, section_pattern: str = DOTTED_SECTION) -> None:
        self._pattern = re.compile(
            rf"\s*(?P<doc>{doc_pattern})?\s*"
            rf"(?:(?:§|::)\s*(?P<section>{section_pattern}))?"
            r"(?:#(?P<anchor>[^\s¶#]+))?"
            r"(?:\s*¶\s*(?P<para>\d+))?"
            r"(?::(?P<first>\d+)-(?P<last>\d+))?\s*"
        )

    def parse(self, text: str) -> Ref:
        """Parse `text`, or raise LibError. A string that names nothing is refused, never guessed at."""
        match = self._pattern.fullmatch(text)
        if match is None or not any(match.group(name) for name in ("doc", "section", "anchor", "first")):
            raise LibError(f"not a ref: {text!r}", "expected <doc>§<section>[#anchor][¶n] or <doc>:<first>-<last>")
        lines: tuple[int, int] | None = None
        if match.group("first"):
            if match.group("section") or match.group("para") or match.group("anchor"):
                raise LibError(f"not a ref: {text!r}", "a line range cannot be combined with a section")
            lines = (int(match.group("first")), int(match.group("last")))
            if lines[0] < 1 or lines[1] < lines[0]:
                raise LibError(f"not a line range: {text!r}", "lines are 1-based and first <= last")
        para = int(match.group("para")) if match.group("para") else None
        if para is not None and para < 1:
            raise LibError(f"not a ref: {text!r}", "¶ is 1-based")
        if para is not None and not (match.group("section") or match.group("anchor")):
            raise LibError(f"not a ref: {text!r}", "¶ needs a section or an anchor to count within")
        return Ref(match.group("doc"), match.group("section"), para, match.group("anchor"), lines)

    @staticmethod
    def format(ref: Ref) -> str:
        """The canonical spelling: no spaces, `§` for the section."""
        out = ref.doc or ""
        if ref.lines is not None:
            return f"{out}:{ref.lines[0]}-{ref.lines[1]}"
        if ref.section is not None:
            out += f"§{ref.section}"
        if ref.anchor is not None:
            out += f"#{ref.anchor}"
        if ref.para is not None:
            out += f"¶{ref.para}"
        return out
