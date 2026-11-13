"""NIST cryptographic test vectors as a primarysource collection: CAVP `.rsp` files and ACVP JSON vector sets.

Vectors are not documents: the unit is a case, and the ref names set, group and case
(`nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3`), so this is its own collection rather than part of `nist`.
Importing this package needs only the standard library; `mcp` is imported only by `server.py` when served.
`docs/cavp.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.cavp.model import format_ref, parse_ref
from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.refs import Ref
from primarysource.registry import Collection


class CavpRefs:
    """The collection's `RefParser`, over `model.parse_ref`: the set id is `doc`, the group `section` and the case
    `anchor` (`nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3`)."""

    def parse(self, text: str) -> Ref:
        ref = parse_ref(text)
        return Ref(ref.set_id, ref.group, None, ref.case)

    def format(self, ref: Ref) -> str:
        if ref.doc is None or ref.para is not None or ref.lines is not None:
            raise LibError(f"not a vector ref: {ref!r}", "a vector ref is a set, optionally a group and a case")
        return format_ref(ref.doc, ref.section, ref.anchor)


COLLECTION = Collection(
    name="cavp",
    title="NIST cryptographic test vectors (CAVP .rsp, ACVP JSON), pinned by sha256",
    prefix="cavp_",
    unit=Unit.BLOCK,
    grammar=CavpRefs(),
    server="primarysource.cavp.server:cavp_server",
    cli="primarysource.cavp.cli:main",
)

__all__ = ["COLLECTION"]
