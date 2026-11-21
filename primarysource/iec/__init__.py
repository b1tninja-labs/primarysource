"""IEC publications for the owner's personal volume, other than ISO and ISO/IEC editions.

`primarysource iec sync --free` orders each free stub and writes the PDF under `pdfs/`. ISO and ISO/IEC heads
are mirrored into the iso home. `primarysource iec import` indexes the IEC publications that are not those
editions: bookmarked PDFs in the home and in `pdfs/`, served by `iec_read`, `iec_search`, `iec_outline`,
`iec_cite` and `iec_docs`. Nothing is redistributed.
"""

from __future__ import annotations

from primarysource.iec.designation import DOC, SECTION
from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection


class _Refs:
    """The collection's ref parser, imported on first use so the collection loads without its reader."""

    _grammar = RefGrammar(DOC, SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.iec.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


IEC = Collection(
    name="iec",
    title="IEC publications (personal volume, other than ISO editions)",
    prefix="iec_",
    unit=Unit.SENTENCE,
    grammar=_Refs(),
    server="primarysource.iec.server:server",
    cli="primarysource.iec.cli:main",
    identify="primarysource.iec.identify:identify",
)
"""Refs: `iec:60835-2-1@1990§1¶2`. `ca-01@2020+csv` is a commented version. `acee-01@2018` is an ACEE document.
ISO and ISO/IEC editions are `iso:` refs."""

__all__ = ["DOC", "IEC", "SECTION"]
