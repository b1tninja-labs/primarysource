"""Ecma International standards, starting with ECMA-427 (Package-URL, 1st edition, December 2025).

Source: the standard's PDF from ecma-international.org, pinned by sha256 in `catalogue.json`, imported into the
user's own `$PRIMARYSOURCE_HOME/ecma/` with `primarysource ecma import 427`. Placement is a volume (Ecma's text
copyright notice allows copies only with the notice and no modification, and Ecma prefers its own download).
Reading the PDF needs `pypdf` (the `[ecma]` extra) at import time only, and uses `pdftotext` for the text when it
is on PATH. `docs/ecma.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection

ECMA_DOC = r"(?:ECMA-|ecma-)?[0-9]{1,4}(?:@[0-9]{1,2})?"
"""A standard by number, optionally with its edition number: `427`, `ECMA-427`, `427@1`."""

ECMA_SECTION = r"[0-9A-Za-z][0-9A-Za-z.\-]*"
"""A clause as the PDF bookmarks number it (`5.3`, `A`, `A.1`) or the slug of an unnumbered bookmark."""


class _Refs:
    """The collection's ref parser: `library.parse_ref` (which also takes the `ecma:` prefix and refuses what the
    collection has no meaning for), imported on first use so the collection loads without its reader."""

    _grammar = RefGrammar(ECMA_DOC, ECMA_SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.ecma.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


ECMA = Collection(
    name="ecma",
    title="Ecma International standards (ECMA-427, Package-URL)",
    prefix="ecma_",
    unit=Unit.SENTENCE,
    grammar=_Refs(),
    server="primarysource.ecma.server:server",
    cli="primarysource.ecma.cli:main",
)
"""Refs: `ecma:427§5.3¶2`. `§` names a clause by its number; `¶n` is the nth sentence of the clause's span (its own
text, then each subsection as a `§5.3.1 Title` line and its text), because a PDF gives sentences, not paragraphs.
The `ecma:` prefix is optional and `ECMA-427` means `427`."""

__all__ = ["ECMA", "ECMA_DOC", "ECMA_SECTION"]
