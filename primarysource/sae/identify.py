"""How the sae collection recognises a recommended practice (`registry.Collection.identify`)."""

from __future__ import annotations

import re

from primarysource.identify import Candidate, Probe, points, score
from primarysource.sae.designation import parse

SAE_DOC = r"j\d+(?:-\d+)?(?:@(?:19|20)\d{2})?"
SAE_SECTION = r"[0-9A-Za-z][0-9A-Za-z.\-]*"

_PRINTED = re.compile(r"SAE[\s._]*J\d+(?:-\d+)?[\s._:]+\d{4}", re.IGNORECASE)


def identify(probe: Probe) -> list[Candidate]:
    """Candidates whose cover, title or file name prints an SAE J designation."""
    out = []
    for value, evidence in score(probe, _PRINTED, lambda match: match.group(0)).items():
        named = parse(value)
        out.append(
            Candidate(
                "sae",
                named.label,
                points(evidence),
                tuple(evidence),
                f'primarysource sae import "{probe.name}" --designation "{named.label}"',
            )
        )
    return out
