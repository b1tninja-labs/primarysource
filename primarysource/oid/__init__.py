"""Root arcs of the international OID tree, taken from the imported X.660.

`primarysource oid roots` reads annex A.2.2 of the owner's ITU copy and prints arcs 0, 1 and 2.
`primarysource oid export` writes the same arcs as `oid-node/1` JSON, which is the file another language reads.
The clause text stays in the ITU library. `docs/oid.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.oid.library import parse_ref
from primarysource.refs import Ref
from primarysource.registry import Collection


class _Refs:
    """`0`, `1`, or `2`, with an optional `oid:` prefix."""

    def parse(self, text: str) -> Ref:
        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return ref.doc or ""


OID = Collection(
    name="oid",
    title="International OID tree, root arcs 0, 1 and 2",
    prefix="oid_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.oid.server:server",
    cli="primarysource.oid.cli:main",
)
"""Refs: `oid:0`, `oid:1`, `oid:2`. Each is one root arc from X.660 §A.2.2."""

__all__ = ["OID"]
