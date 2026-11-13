"""How the ieee802 collection recognises an IEEE 802 standard in a supplied PDF (`registry.Collection.identify`).

Covers and running headers read `IEEE Std 802.1Q-2022`. The importer takes the user's own PDF and the designation.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates

_STD = re.compile(r"\bIEEE\s+Std\.?\s+(?P<designation>802(?:\.\d{1,2}[A-Za-z]{0,4})*-\d{4})\b")


def _label(match: re.Match[str]) -> str:
    return f"IEEE Std {match['designation']}"


def identify(probe: Probe) -> list[Candidate]:
    def command(label: str) -> str:
        where = probe.path if probe.path is not None else probe.name
        return f'primarysource ieee802 import "{where}" {label.removeprefix("IEEE Std ")}'

    return candidates(probe, "ieee802", _STD, _label, command)
