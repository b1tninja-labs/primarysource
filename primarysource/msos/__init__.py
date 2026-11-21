"""Microsoft Open Specifications: the four families on [MS-OPENSPECLP].

Protocols, computer languages, standards support, and data portability. `primarysource msos sync` downloads
the PDF zip each family page links to. `primarysource msos import` indexes those PDFs. The documents stay in
the collection home. Microsoft's own notice allows copies for implementing the technologies; this package
does not redistribute the text.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.msos.library import DOC, SECTION
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection


class _Refs:
    _grammar = RefGrammar(DOC, SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.msos.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


MSOS = Collection(
    name="msos",
    title="Microsoft Open Specifications",
    prefix="msos_",
    unit=Unit.SENTENCE,
    grammar=_Refs(),
    server="primarysource.msos.server:server",
    cli="primarysource.msos.cli:main",
)
"""Refs: `msos:ms-patch§2.1¶2`. `[MS-PATCH]` is the same document. `¶n` is the nth sentence of the clause."""

__all__ = ["MSOS"]
