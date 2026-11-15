"""Bluetooth SIG specifications, fetched by the user from bluetooth.com and indexed locally.

`primarysource bluetooth catalogue` reads the SIG's list of specifications (about 265: the Core Specification
versions, profiles, services, mesh, supplements); `primarysource bluetooth fetch` downloads the PDFs named, pins
each by sha256, extracts and indexes them. The PDFs stay in the collection's home (`$PRIMARYSOURCE_BLUETOOTH_HOME`):
the SIG licenses non-members to use its content to evaluate Bluetooth technology, so the text is never in this
repository or an image. `docs/bluetooth.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.pdfcorpus.tools import GRAMMAR
from primarysource.refs import Ref
from primarysource.registry import Collection

REF_PREFIX = "bluetooth:"


class _Refs:
    """`GRAMMAR` with the optional `bluetooth:` prefix."""

    def parse(self, text: str) -> Ref:
        bare = text.strip()
        if bare.lower().startswith(REF_PREFIX):
            bare = bare[len(REF_PREFIX) :]
        return GRAMMAR.parse(bare)

    def format(self, ref: Ref) -> str:
        return REF_PREFIX + GRAMMAR.format(ref)


COLLECTION = Collection(
    name="bluetooth",
    title="Bluetooth SIG specifications (Core, profiles, services), fetched by the user",
    prefix="bluetooth_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.bluetooth.server:mcp",
    cli="primarysource.bluetooth.cli:main",
)
"""Refs: `bluetooth:battery-service§3.1`, or a line range `bluetooth:battery-service:10-40`."""

__all__ = ["COLLECTION", "REF_PREFIX"]
