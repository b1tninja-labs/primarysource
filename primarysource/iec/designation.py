"""IEC designations, as printed (`IEC 60835-2-1:1990`, `IEC CA 01:2020 CSV`, `IEC ACEE 01:2018`).

An ISO or ISO/IEC designation is not an IEC designation: those editions are the iso collection's. The document
id is `<number>@<year>` (`60835-2-1@1990`), `ca-01@2020+csv` for a commented version, and `acee-01@2018` for an
ACEE operational document. `:` already means a line range in a ref, so it is not part of the id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource.errors import LibError

_PATTERN = re.compile(
    r"(?<!ISO[/ _])IEC"
    r"(?:[/_ ](?P<series>CA|ACEE))?"
    r"[/_ ]+(?P<number>\d{1,5}(?:-\d{1,3})*)"
    r"[_:\- ]+(?P<year>(?:19|20)\d{2})"
    r"(?:[/_ ]+(?P<csv>CSV))?",
    re.IGNORECASE,
)

DOC = r"(?:(?:ca|acee)-)?\d{1,5}(?:-\d{1,3})*(?:@(?:19|20)\d{2}(?:\+csv)?)?"
"""A document id in a ref: `60835-2-1`, `60835-2-1@1990`, `ca-01@2020+csv`."""

SECTION = r"[0-9A-Za-z][0-9A-Za-z.\-]*"
"""A clause as the PDF's bookmarks number it (`5.3`, `A`) or the slug of an unnumbered bookmark."""


@dataclass(frozen=True, slots=True)
class Designation:
    series: str
    number: str
    year: int
    csv: bool = False

    @property
    def label(self) -> str:
        """The designation as IEC prints it: `IEC CA 01:2020 CSV`."""
        head = "IEC" + (f" {self.series}" if self.series else "")
        tail = " CSV" if self.csv else ""
        return f"{head} {self.number}:{self.year}{tail}"

    @property
    def doc(self) -> str:
        """The id refs use: `60835-2-1@1990`, `ca-01@2020+csv`."""
        prefix = f"{self.series.lower()}-" if self.series else ""
        suffix = "+csv" if self.csv else ""
        return f"{prefix}{self.number}@{self.year}{suffix}"

    @property
    def key(self) -> str:
        """The doc id as a file name: `60835-2-1_1990`, `ca-01_2020_csv`."""
        return self.doc.replace("@", "_").replace("+", "_")


def _from_match(match: re.Match[str]) -> Designation:
    series = (match["series"] or "").upper()
    return Designation(series, match["number"], int(match["year"]), bool(match["csv"]))


def parse(text: str) -> Designation:
    """A designation as printed (`IEC 60835-2-1:1990`), or a `LibError` that shows the expected form."""
    match = _PATTERN.fullmatch(text.strip())
    if match is None:
        raise LibError(
            f"not an IEC designation: {text!r}",
            "write it as printed, e.g. 'IEC 60835-2-1:1990', 'IEC CA 01:2020 CSV' or 'IEC ACEE 01:2018'",
        )
    return _from_match(match)


def from_filename(name: str) -> Designation | None:
    """The designation in a store file name (`IEC_60835-2-1_1990.pdf`), or None."""
    stem = re.sub(r"\.(?:pdf|zip)$", "", name.strip(), flags=re.IGNORECASE)
    match = _PATTERN.fullmatch(stem.replace("_", " "))
    if match is None:
        return None
    return _from_match(match)


def split_doc(token: str) -> tuple[str, str | None]:
    """`60835-2-1@1990` into `('60835-2-1', '1990')`; a bare number into `(number, None)`."""
    number, sep, rest = token.partition("@")
    return number, rest if sep else None
