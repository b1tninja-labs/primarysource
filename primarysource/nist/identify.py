"""How the nist collection recognises a NIST publication in a supplied PDF (`registry.Collection.identify`).

Covers read `NIST Special Publication 800-53` with `Revision 5` near it, or `FIPS PUB 201-3`; running headers
and DOIs repeat `NIST SP 800-53r5`. The nist collection fetches its own pinned copies (`data/sources.toml`), so
the command it suggests is the fetch.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates

_SP = re.compile(
    r"\bNIST\s+(?:Special\s+Publication|SP)\s+(?P<num>800-\d{1,3}(?:(?-i:[A-Z])(?!\d))?)"
    r"(?:(?:\s*,?\s*(?:Revision|Rev\.?)\s*|r)(?P<rev>\d{1,2}))?",
    re.IGNORECASE,
)
_FIPS = re.compile(
    r"\b(?:FIPS|Federal\s+Information\s+Processing\s+Standards?\s+Publication)\s+(?:PUB\s+)?(?P<num>\d{2,3}(?:-\d{1,2})?)\b",
    re.IGNORECASE,
)


def _sp(match: re.Match[str]) -> str:
    rev = f" Rev. {match['rev']}" if match["rev"] else ""
    return f"NIST SP {match['num'].upper()}{rev}"


def _fips(match: re.Match[str]) -> str:
    return f"NIST FIPS {match['num']}"


def identify(probe: Probe) -> list[Candidate]:
    def command(_label: str) -> str:
        return "primarysource nist fetch  (nist fetches its own pinned copies listed in data/sources.toml)"

    return [
        *candidates(probe, "nist", _SP, _sp, command),
        *candidates(probe, "nist", _FIPS, _fips, command),
    ]
