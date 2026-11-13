"""ISO designations, as printed (`ISO/IEC 9899:2024`, `ISO 8601-1:2019/Amd 1:2022`, `ISO/IEC TR 24772-1:2019`) and
as the ISO store names its files (`ISO_IEC_9899_2024(en).pdf`).

The collection's document id is `<number>@<year>` (`9899@2024`, `8601-1@2019`), with `+amd1-2022` or `+cor1-2022`
for an amendment or a corrigendum. It is not the designation itself, because `:` already means a line range in a
ref and `/` is not a safe file name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource.errors import LibError

_PATTERN = re.compile(
    r"(?P<pub>ISO(?:[/_ ]IEC)?(?:[/_ ]IEEE)?)"
    r"(?:[/_ ](?P<kind>TS|TR|PAS|Guide))?"
    r"[/_ ]+(?P<number>\d{1,5}(?:-\d{1,3})*)"
    r"[_:\- ](?P<year>(?:19|20)\d{2})"
    r"(?:\s*[/_ ]\s*(?P<supp>Amd|Cor)[_ .]*(?P<sn>\d{1,2})[_:\- ](?P<syear>(?:19|20)\d{2}))?",
    re.IGNORECASE,
)

DOC = r"\d{1,5}(?:-\d{1,3})*(?:@(?:19|20)\d{2}(?:\+(?:amd|cor)\d{1,2}-(?:19|20)\d{2})?)?"
"""A document id in a ref: `9899`, `9899@2024`, `27001@2022+amd1-2024`."""

_DOC = re.compile(r"(?P<number>\d{1,5}(?:-\d{1,3})*)(?:@(?P<rest>.+))?")


@dataclass(frozen=True, slots=True)
class Designation:
    publisher: str
    kind: str
    number: str
    year: int
    supplement: str = ""
    """`Amd 1:2022` or `Cor 1:2022`, or empty for the standard itself."""

    @property
    def label(self) -> str:
        """The designation as ISO prints it: `ISO/IEC TR 24772-1:2019/Amd 1:2022`."""
        head = self.publisher + (f" {self.kind}" if self.kind else "")
        tail = f"/{self.supplement}" if self.supplement else ""
        return f"{head} {self.number}:{self.year}{tail}"

    @property
    def doc(self) -> str:
        """The id refs use: `9899@2024`, `27001@2022+amd1-2024`."""
        suffix = ""
        if self.supplement:
            kind, _, rest = self.supplement.partition(" ")
            number, _, year = rest.partition(":")
            suffix = f"+{kind.lower()}{number}-{year}"
        return f"{self.number}@{self.year}{suffix}"

    @property
    def key(self) -> str:
        """The doc id as a file name: `9899_2024`, `27001_2022_amd1-2024`."""
        return self.doc.replace("@", "_").replace("+", "_")


def _from_match(match: re.Match[str]) -> Designation:
    publisher = "/".join(part.upper() for part in re.split(r"[/_ ]", match["pub"]))
    kind = match["kind"] or ""
    kind = "Guide" if kind.lower() == "guide" else kind.upper()
    supplement = ""
    if match["supp"]:
        supplement = f"{match['supp'].capitalize()} {int(match['sn'])}:{match['syear']}"
    return Designation(publisher, kind, match["number"], int(match["year"]), supplement)


def parse(text: str) -> Designation:
    """A designation as printed (`ISO/IEC 9899:2024`), or a `LibError` that shows the expected form."""
    match = _PATTERN.fullmatch(text.strip())
    if match is None:
        raise LibError(
            f"not an ISO designation: {text!r}",
            "write it as printed on the cover, e.g. 'ISO/IEC 9899:2024' or 'ISO 8601-1:2019/Amd 1:2022'",
        )
    return _from_match(match)


def from_filename(name: str) -> Designation | None:
    """The designation an ISO store file name carries (`ISO_IEC_9899_2024(en).pdf`), or None."""
    match = _PATTERN.search(name)
    return _from_match(match) if match else None


def split_doc(token: str) -> tuple[str, str | None]:
    """A ref's document token as (number, the part after `@` or None): `9899@2024` is ('9899', '2024')."""
    match = _DOC.fullmatch(token.strip())
    if match is None or not re.fullmatch(DOC, token.strip()):
        raise LibError(f"not an ISO document: {token!r}", "use the number and year, e.g. 9899@2024, or just 9899")
    return match["number"], match["rest"]
