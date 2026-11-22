"""The Bosch CAN Specification 2.0, from the owner's own copy of the PDF.

A local-only volume on the shared `primarysource.localpdf` mechanism, behind the terms-acknowledgement gate
(`primarysource.terms`): `primarysource can import` refuses unless `PRIMARYSOURCE_CAN_ACCEPT_TERMS` says the owner
has read Bosch's terms for the file and accepts them. The PDF's own second page says the document as a whole may be
copied and distributed without restrictions, but that use in parts or as a whole in other documents needs the
consent of Robert Bosch GmbH (`docs/can.md` says exactly what was read and what was not). This package does not ship
the PDF. The CAN FD specification carries no such statement and is not covered. Bosch's terms URL was not
verified, so the gate names none.
"""

from __future__ import annotations

import re

from primarysource.localpdf import LocalPdfSpec, LocalRefs
from primarysource.localpdf.spec import DocId
from primarysource.model import Unit
from primarysource.registry import Collection
from primarysource.terms import Terms

TERMS = Terms("can", "Robert Bosch GmbH", None)

_CAN20 = re.compile(r"^can[ _-]?2[._-]?0\b.*\.pdf$", re.IGNORECASE)


def name_file(name: str, digest: str) -> DocId | None:
    """`can20.pdf` (the name the PDF circulates under) is `bosch-2.0`. `digest` is not needed."""
    if _CAN20.match(name):
        return DocId("bosch-2.0", "bosch-2.0", "Bosch CAN Specification 2.0", "CAN Specification 2.0")
    return None


SPEC = LocalPdfSpec(
    name="can",
    title="Bosch CAN specification",
    terms=TERMS,
    name_file=name_file,
    instructions=(
        "The Bosch CAN Specification 2.0 (Part A and Part B), from the user's own copy of the PDF. Loop: "
        "can_search('<words>') -> can_read('<ref>'). Refs: 'can:bosch-2.0§3.1' (a bookmarked clause; Part A and "
        "Part B repeat clause numbers, the second occurrence of 3.1 is '3.1-1'), '...¶3' (from its 3rd sentence). "
        "can_outline('bosch-2.0') lists clauses as refs. Every tool refuses until the owner has set "
        "PRIMARYSOURCE_CAN_ACCEPT_TERMS; the error says what to do."
    ),
    ref_example="can:bosch-2.0§3.1¶2",
    front_matter=True,
)

CAN = Collection(
    name="can",
    title="Bosch CAN Specification 2.0 from the owner's own PDF",
    prefix="can_",
    unit=Unit.SENTENCE,
    grammar=LocalRefs(SPEC),
    server="primarysource.can.server:server",
    cli="primarysource.can.cli:main",
    identify="primarysource.can.identify:identify",
)
"""Refs: `can:bosch-2.0§3.1¶2`: the document, a clause as the PDF's bookmarks number it (a second occurrence of a
number, in Part B, is `3.1-1`), and `¶n`, the nth sentence of the clause's span."""

__all__ = ["CAN", "SPEC", "TERMS"]
