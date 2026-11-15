"""How the can collection recognises the Bosch CAN Specification 2.0 in a PDF (`registry.Collection.identify`).

Its cover prints `CAN Specification` and `Version 2.0` on separate lines, so the cover pattern spans the line break.
The CAN FD specification's cover reads differently and is not matched: it is a different document, and the grant
in the 2.0 file (`docs/can.md`) does not extend to it.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates

_COVER = re.compile(r"\bCAN\s+Specification\s+Version\s+2\.0\b", re.IGNORECASE)
DESIGNATION = "Bosch CAN Specification 2.0"


def identify(probe: Probe) -> list[Candidate]:
    """The CAN 2.0 designation when the cover (or a later page, or the title metadata) says so."""

    def command(_label: str) -> str:
        where = f'"{probe.path}"' if probe.path is not None else f'"{probe.name}"'
        return f"primarysource can import {where}"

    return candidates(probe, "can", _COVER, lambda _m: DESIGNATION, command)
