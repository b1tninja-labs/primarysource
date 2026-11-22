"""How the gm collection recognises GM's Mode $06 definition files in a supplied PDF (`registry.Collection.identify`).

The two Mode $06 files state on their first page which data link they are for (`for GM vehicles using GMLAN
diagnostic data link`, `... using J1850/Class2 diagnostic data link`). The 17OBDG parameter files open straight
into a table and say nothing that names them, so they are recognised by file name at import (`gm.name_file`), not
here: guessing them from table headers would be a fragile heuristic.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates

_MODE6 = re.compile(
    r"mode\s+\$06\s+data\s+definitions\s+for\s+GM\s+vehicles\s+using\s+(?P<bus>GMLAN|J1850/Class2)", re.IGNORECASE
)
LABELS = {"gmlan": "GM Mode $06 CAN (GMLAN)", "j1850/class2": "GM Mode $06 Class2 (J1850)"}


def identify(probe: Probe) -> list[Candidate]:
    """The Mode $06 file for the data link the first page names."""

    def command(_label: str) -> str:
        where = f'"{probe.path}"' if probe.path is not None else f'"{probe.name}"'
        return f"primarysource gm import {where}"

    return candidates(probe, "gm", _MODE6, lambda m: LABELS[m["bus"].lower()], command)
