"""How the itu collection recognises an ITU-T Recommendation in a supplied PDF (`registry.Collection.identify`).

A cover reads `Recommendation ITU-T X.690` and pages carry `Rec. ITU-T X.690 (02/2021)`; ITU's own download is
named `T-REC-X.690-202102-I!!PDF-E.pdf`. The itu collection fetches its own pinned copy, so the command it
suggests is the fetch, not an import of this file.
"""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, candidates

_TEXT = re.compile(r"\b(?:Rec(?:ommendation)?\.?\s+)?ITU-T\s+(?P<rec>[A-Z]\.\d{1,4}(?:\.\d{1,3})?)\b")
_FILE = re.compile(r"T-REC-(?P<rec>[A-Z]\.\d{1,4}(?:\.\d{1,3})?)-")


def _rec(match: re.Match[str]) -> str:
    return f"Rec. ITU-T {match['rec']}"


def identify(probe: Probe) -> list[Candidate]:
    def command(label: str) -> str:
        return f"primarysource itu fetch {label.rsplit(' ', 1)[-1]}  (itu fetches its own pinned copy)"

    return candidates(probe, "itu", _TEXT, _rec, command, file_pattern=_FILE)
