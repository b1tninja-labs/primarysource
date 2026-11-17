"""General Motors VIN standards filed with NHTSA under 49 CFR Part 565.

The PDFs stay in the collection's home (`$PRIMARYSOURCE_VIN_HOME`, else `$PRIMARYSOURCE_HOME/vin`) and are
imported with `primarysource vin import`. Nothing here fetches, and nothing copies a PDF into the package.
The filings name the ISO vehicle-identification standard and do not give an ISO number; a document's label is
`GM VIN standard <year>`. `docs/vin.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection
from primarysource.vin.identify import VIN_DOC, VIN_SECTION


class _Refs:
    """The collection's ref parser: `library.parse_ref`, imported on first use so the collection loads without
    its reader."""

    _grammar = RefGrammar(VIN_DOC, VIN_SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.vin.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


VIN = Collection(
    name="vin",
    title="General Motors VIN standards filed with NHTSA under 49 CFR Part 565",
    prefix="vin_",
    unit=Unit.SENTENCE,
    grammar=_Refs(),
    server="primarysource.vin.server:server",
    cli="primarysource.vin.cli:main",
    identify="primarysource.vin.identify:identify",
)
"""Refs: `vin:gm-vin-2016§33`. The document id is `gm-vin-<year>`. The section is the 1-based PDF page.
`¶n` is the nth line of that page."""

__all__ = ["VIN", "VIN_DOC", "VIN_SECTION"]
