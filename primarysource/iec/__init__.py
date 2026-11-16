"""IEC Webstore free publications for the owner's personal volume.

`primarysource iec sync --free` orders each free stub in `$PRIMARYSOURCE_HOME/iec/webstore/stubs` and writes
the PDF under `pdfs/`. ISO and ISO/IEC heads are also mirrored into the iso home for `primarysource iso import`.
Nothing is redistributed: files stay on the buyer's machine only.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

# Sync-only for now: no reader or MCP tools until an iec importer lands beside iso's.
IEC = Collection(
    name="iec",
    title="IEC Webstore free publications (personal volume)",
    prefix="iec_",
    unit=Unit.SENTENCE,
    grammar=RefGrammar(r"[A-Za-z0-9][A-Za-z0-9.\-]*", r"[0-9A-Za-z][0-9A-Za-z.\-]*"),
    cli="primarysource.iec.cli:main",
)

__all__ = ["IEC"]
