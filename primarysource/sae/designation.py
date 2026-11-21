"""SAE designations as printed (`SAE J2534:2002`, `SAE J2534-1:2004`) and as a file name
(`sae.j2534.2002.pdf`).

The document id is `j2534@2002`. The colon in the printed year is not used in a ref, because `:` already
means a line range.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource.errors import LibError

_PATTERN = re.compile(
    r"SAE[\s._]*J(?P<number>\d+(?:-\d+)?)[\s._:]+(?P<year>(?:19|20)\d{2})",
    re.IGNORECASE,
)

DOC = r"j\d+(?:-\d+)?(?:@(?:19|20)\d{2})?"
"""A document id in a ref: `j2534`, `j2534@2002`, `j2534-1@2004`."""


@dataclass(frozen=True, slots=True)
class Designation:
    number: str
    year: int

    @property
    def label(self) -> str:
        return f"SAE J{self.number}:{self.year}"

    @property
    def doc(self) -> str:
        return f"j{self.number}@{self.year}"

    @property
    def key(self) -> str:
        return f"j{self.number}_{self.year}"


def parse(text: str) -> Designation:
    """The designation printed in `text`, or a LibError naming the form that works."""
    match = _PATTERN.search(text.strip())
    if match is None:
        raise LibError(
            f"{text!r} is not an SAE designation",
            "",
            'use the cover form, for example "SAE J2534:2002"',
        )
    return Designation(match.group("number"), int(match.group("year")))


def from_filename(name: str) -> Designation | None:
    """The designation a `sae.j2534.2002.pdf` style name carries, or None."""
    match = _PATTERN.search(name)
    return Designation(match.group("number"), int(match.group("year"))) if match else None
