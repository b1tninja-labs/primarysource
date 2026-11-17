"""How the vin collection recognises a General Motors VIN filing (`registry.Collection.identify`).

These are GM's vehicle-identification standards as filed with NHTSA under 49 CFR Part 565. The cover letter
states the model year and the Part 565 cite (the 2016 letter cites 565.7; the 2017–2019 letters cite 565.16(c)).
The filings name CMVSS 115 and the ISO vehicle-identification standard and do not give an ISO number, so a match
here is `GM VIN standard <year>`, never an ISO designation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource.identify import Candidate, Probe, points

VIN_DOC = r"gm-vin-(?:19|20)\d{2}"
"""A document id in a ref: `gm-vin-2016`."""

VIN_SECTION = r"[0-9]+"
"""A section id: the 1-based PDF page, which is how these filings are cut."""

_WS = re.compile(r"\s+")
_PHRASE = re.compile(
    r"Vehicle Identification Numbering \(VIN\) Standard for the (?P<year>(?:19|20)\d{2}) Model Year",
    re.IGNORECASE,
)
_CFR = re.compile(r"49 CFR Part 565(?:\.\d+(?:\([A-Za-z]\))?)?", re.IGNORECASE)
_GM = re.compile(r"General Motors", re.IGNORECASE)
_FILENAME = re.compile(r"gm-vin-(?P<year>(?:19|20)\d{2})", re.IGNORECASE)


def flat(text: str) -> str:
    """Newlines and runs of spaces collapsed, so a cite split across two lines still matches."""
    return _WS.sub(" ", text).strip()


def part565(text: str) -> str:
    """The Part 565 cite printed in `text` (`49 CFR Part 565.7`, `49 CFR Part 565.16(c)`), or ""."""
    match = _CFR.search(flat(text))
    return match.group(0) if match else ""


@dataclass(frozen=True, slots=True)
class Filing:
    """One model-year filing. The id is `gm-vin-<year>`, the same id the shelf already uses."""

    year: int

    @property
    def label(self) -> str:
        return f"GM VIN standard {self.year}"

    @property
    def doc(self) -> str:
        return f"gm-vin-{self.year}"

    @property
    def key(self) -> str:
        return self.doc


def filing_from_label(label: str) -> Filing:
    """The filing a `GM VIN standard <year>` label names."""
    match = re.fullmatch(r"GM VIN standard (?P<year>(?:19|20)\d{2})", label.strip())
    if match is None:
        raise ValueError(label)
    return Filing(int(match["year"]))


def from_filename(name: str) -> Filing | None:
    """The filing a `gm-vin-<year>` file name names, or None."""
    match = _FILENAME.search(name)
    return Filing(int(match["year"])) if match else None


def identify(probe: Probe) -> list[Candidate]:
    """The GM filing this probe is, when its cover states the VIN standard for a model year and cites 49 CFR
    Part 565. The publisher is General Motors, or the file is already named `gm-vin-<year>`."""
    if not probe.pages:
        return []
    cover = flat(probe.pages[0])
    phrase = _PHRASE.search(cover)
    cite = part565(cover)
    if phrase is None or not cite:
        return []
    year = int(phrase["year"])
    named = from_filename(probe.name)
    if _GM.search(cover) is None and (named is None or named.year != year):
        return []
    evidence = ["cover", "49 CFR Part 565"]
    if named is not None and named.year == year:
        evidence.append("file name")
    filing = Filing(year)
    where = f'"{probe.path}"' if probe.path is not None else f'"{probe.name}"'
    return [
        Candidate(
            "vin",
            filing.label,
            points(evidence),
            tuple(evidence),
            f"primarysource vin import {where}",
        )
    ]
