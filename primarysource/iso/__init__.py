"""ISO standards from the owner's own purchased PDFs.

Placement is a personal volume: the files are the buyer's single-user copies, dropped into
`$PRIMARYSOURCE_HOME/iso/purchased/` and imported with `primarysource iso import`. Nothing here fetches, nothing is
copied into an image, and the PDF itself is not copied: the import stores the extracted text and a record of the
source (sha256, size, mtime), and builds the core FTS5 index. Reading a PDF needs `pypdf` (the `[iso]` extra) at
import time only; serving reads the stored extraction. `docs/iso.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.iso.designation import DOC as ISO_DOC
from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection

ISO_SECTION = r"[0-9A-Za-z][0-9A-Za-z.\-]*"
"""A clause as the PDF bookmarks number it (`6.5.2`, `A`, `A.1`) or the slug of an unnumbered bookmark."""


class _Refs:
    """The collection's ref parser: `library.parse_ref` (which also takes the `iso:` prefix and a printed
    designation), imported on first use so the collection loads without its reader."""

    _grammar = RefGrammar(ISO_DOC, ISO_SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.iso.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


ISO = Collection(
    name="iso",
    title="ISO standards from the owner's own purchased PDFs",
    prefix="iso_",
    unit=Unit.SENTENCE,
    grammar=_Refs(),
    server="primarysource.iso.server:server",
    cli="primarysource.iso.cli:main",
)
"""Refs: `iso:9899@2024§6.5.2¶3`. The document is `<number>@<year>` (the newest imported year when omitted); a
printed designation such as `ISO/IEC 9899:2024§6.5.2` is accepted too. `¶n` is the nth sentence of the clause's
span, because a PDF gives sentences, not paragraphs."""

__all__ = ["ISO", "ISO_DOC", "ISO_SECTION"]
