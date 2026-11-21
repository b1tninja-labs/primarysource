"""SAE documents from the owner's own PDFs.

The PDF stays where the owner keeps it. `primarysource sae import` writes the extraction and the search
index under `$PRIMARYSOURCE_HOME/sae` (or `$PRIMARYSOURCE_SAE_HOME`). Nothing is fetched and nothing is
copied into this package.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection
from primarysource.sae.designation import DOC
from primarysource.sae.identify import SAE_SECTION


class _Refs:
    _grammar = RefGrammar(DOC, SAE_SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.sae.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


SAE = Collection(
    name="sae",
    title="SAE documents from the owner's own PDFs",
    prefix="sae_",
    unit=Unit.SENTENCE,
    grammar=_Refs(),
    server="primarysource.sae.server:server",
    cli="primarysource.sae.cli:main",
    identify="primarysource.sae.identify:identify",
)

__all__ = ["SAE"]
