"""Document ids and citation names for GM's published OBD files, derived from the file name.

GM names the files by model-year OBD group and module (`17OBDG01 Hybrid Diagnostics.pdf`), and the two Mode $06
references by the data link (`GM CAN mode $06 data final_dm.pdf`). The id is what a ref names: `gm:17OBDG01-hybrid`,
`gm:mode6-can`. A browser's ` (1)` copy suffix is ignored, and GM's own spelling `Transmisson` is read as
`transmission`. A name this module does not know is refused with the remedy (`--id`), never guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from primarysource.errors import LibError

_GROUP = re.compile(
    r"^(?P<year>\d{2})\s*OBDG(?P<group>\d{2})\s+(?P<kind>Hybrid|Engine|Trans\w*)\s+Diagnostics$", re.IGNORECASE
)
_SUMMARY = re.compile(r"^(?P<year>\d{4})[_ ]OBD[_ ]GROUP[_ ]SUMMARY$", re.IGNORECASE)
_MODE6 = re.compile(r"^GM\s+(?P<link>CAN|Class2)\s+mode\s+\$06\b", re.IGNORECASE)
_COPY = re.compile(r"\s*\(\d+\)$")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_KIND = {"hybrid": "Hybrid", "engine": "Engine", "transmission": "Transmission"}


@dataclass(frozen=True, slots=True)
class Designation:
    """How one file is cited: `doc_id` in a ref, `number` in a citation line, `title` for people."""

    doc_id: str
    number: str
    title: str
    year: str


def designate(file_name: str, doc_id: str | None = None) -> Designation:
    """The designation of a file by its name. `doc_id` overrides the id for a file whose name is not recognised."""
    stem = file_name[:-4] if file_name.lower().endswith(".pdf") else file_name
    stem = _COPY.sub("", stem).strip()
    found: Designation | None = None
    if (m := _GROUP.match(stem)) is not None:
        kind = "transmission" if m["kind"].lower().startswith("trans") else m["kind"].lower()
        code = f"{m['year']}OBDG{m['group']}"
        found = Designation(
            f"{code}-{kind}",
            f"GM {code} {_KIND[kind]} Diagnostics",
            f"20{m['year']} OBD Group {int(m['group'])} {_KIND[kind].lower()} diagnostic parameter file",
            f"20{m['year']}",
        )
    elif (m := _SUMMARY.match(stem)) is not None:
        found = Designation(
            f"{m['year']}-group-summary",
            f"GM {m['year']} OBD Group Summary",
            f"{m['year']} engine and transmission diagnostic parameter file matrix",
            m["year"],
        )
    elif (m := _MODE6.match(stem)) is not None:
        link = "CAN" if m["link"].lower() == "can" else "Class2"
        found = Designation(
            f"mode6-{link.lower()}",
            f"GM Mode $06 data definitions ({link})",
            f"mode $06 data definitions for GM vehicles on the {link} data link",
            "",
        )
    if doc_id is not None:
        if _ID.fullmatch(doc_id) is None:
            raise LibError(f"{doc_id!r} is not a document id", "use letters, digits, '.', '_' and '-'")
        base = found or Designation(doc_id, f"GM {stem}", stem, "")
        return Designation(doc_id, base.number, base.title, base.year)
    if found is None:
        raise LibError(
            f"{file_name!r} is not a GM OBD file name this collection recognises",
            "import it with `primarysource gm import FILE --id <doc-id>`",
        )
    return found
