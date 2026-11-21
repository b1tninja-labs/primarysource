"""How the iec collection recognises an IEC publication that is not an ISO edition.

The cover and the running header outweigh the file name. `ISO/IEC 5230:2020` is an ISO designation and is not
reported here; the iso collection already indexes those editions.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates, points
from primarysource.iec.designation import _PATTERN, Designation, _from_match

_FILE = re.compile(_PATTERN.pattern, _PATTERN.flags)


def _label(match: re.Match[str]) -> str | None:
    return _from_match(match).label


def designation_of(label: str) -> Designation:
    match = _PATTERN.fullmatch(label)
    if match is None:
        raise ValueError(label)
    return _from_match(match)


def _merge(found: list[Candidate]) -> list[Candidate]:
    """One candidate per document. A commented version and the same number without CSV are one document,
    spelled with CSV when either source says so."""
    by_base: dict[str, list[Candidate]] = {}
    for candidate in found:
        base = designation_of(candidate.designation).doc.split("+", 1)[0]
        by_base.setdefault(base, []).append(candidate)
    merged: list[Candidate] = []
    for group in by_base.values():
        best = max(group, key=lambda item: (item.designation.endswith("CSV"), item.score))
        evidence = tuple(dict.fromkeys(item for candidate in group for item in candidate.evidence))
        merged.append(Candidate(best.collection, best.designation, points(evidence), evidence, best.command))
    return merged


def identify(probe: Probe) -> list[Candidate]:
    """IEC designations in the probe. An ISO/IEC designation produces none."""

    def command(label: str) -> str:
        where = f'"{probe.path}"' if probe.path is not None else f'"{probe.name}"'
        return f'primarysource iec import {where} --designation "{label}"'

    return _merge(candidates(probe, "iec", _PATTERN, _label, command, file_pattern=_FILE))
