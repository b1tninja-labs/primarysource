"""How the ecma collection recognises an Ecma standard in a supplied PDF (`registry.Collection.identify`).

Covers and running headers read `ECMA-427` (`Standard ECMA-427`); Ecma's download is `ECMA-427_1st_edition.pdf`.
The importer takes the file the user downloaded (`--file`) and checks it against the catalogue's pinned digest.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates

_ECMA = re.compile(r"\bECMA-(?P<num>\d{1,4})\b")


def _label(match: re.Match[str]) -> str:
    return f"ECMA-{match['num']}"


def identify(probe: Probe) -> list[Candidate]:
    def command(label: str) -> str:
        where = probe.path if probe.path is not None else probe.name
        return f'primarysource ecma import {label.removeprefix("ECMA-")} --file "{where}"'

    return candidates(probe, "ecma", _ECMA, _label, command)
