"""GM's own published OBD documents, indexed from the owner's local copies.

Placement is a personal volume: the PDFs GM publishes for the aftermarket (Mode $06 definitions and the per-group
diagnostic parameter files) stay in the collection's home (`$PRIMARYSOURCE_GM_HOME`) and are never copied into this
repository or an image. `primarysource gm import` reads them with `pypdf` and `pdftotext` once, writes the text
and a section index beside them, and serves them over stdio. `docs/gm.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.pdfcorpus.tools import GRAMMAR
from primarysource.refs import Ref
from primarysource.registry import Collection

REF_PREFIX = "gm:"


class _Refs:
    """`GRAMMAR` with the optional `gm:` prefix: `gm:mode6-can§01-02` and `mode6-can§01-02` are one ref."""

    def parse(self, text: str) -> Ref:
        bare = text.strip()
        if bare.lower().startswith(REF_PREFIX):
            bare = bare[len(REF_PREFIX) :]
        return GRAMMAR.parse(bare)

    def format(self, ref: Ref) -> str:
        return REF_PREFIX + GRAMMAR.format(ref)


COLLECTION = Collection(
    name="gm",
    title="GM's own published OBD documents (Mode $06, diagnostic parameter files), from local copies",
    prefix="gm_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.gm.server:mcp",
    cli="primarysource.gm.cli:main",
)
"""Refs: `gm:17OBDG01-hybrid§P0010`, `gm:mode6-can§01-02`, or a line range `gm:mode6-can:10-40`."""

__all__ = ["COLLECTION", "REF_PREFIX"]
