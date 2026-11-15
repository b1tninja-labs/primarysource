"""GM's 2017 OBD diagnostic parameter files and Mode $06 definitions, from the owner's own copies of the PDFs.

A local-only volume on the shared `primarysource.localpdf` mechanism, behind the terms-acknowledgement gate
(`primarysource.terms`): the owner puts the PDFs in the collection's home (`$PRIMARYSOURCE_GM_HOME`, else
`$PRIMARYSOURCE_HOME/gm`) and imports them with `primarysource gm import`, which refuses unless
`PRIMARYSOURCE_GM_ACCEPT_TERMS` says the owner has read GM's terms for the files and accepts them. The files are
tables, not prose, so each is cut one section per page (`readers.bookmarks.cut_pages`); `docs/gm.md` says what a
search hit and a ref look like. The PDF is never copied. GM's terms URL was not verified, so the gate names none.
"""

from __future__ import annotations

import re

from primarysource.localpdf import LocalPdfSpec, LocalRefs
from primarysource.localpdf.spec import DocId
from primarysource.model import Unit
from primarysource.registry import Collection
from primarysource.terms import Terms

TERMS = Terms("gm", "General Motors", None)

_GROUP = re.compile(
    r"^17OBDG(?P<group>\d\d)\s+(?P<kind>Hybrid|Engine|Transmi\w+)\s+Diagnostics?(?:\s*\(\d+\))?\.pdf$", re.IGNORECASE
)
_SUMMARY = re.compile(r"^2017[ _]OBD[ _]GROUP[ _]SUMMARY\.pdf$", re.IGNORECASE)
_MODE6 = re.compile(r"^GM\s+(?P<bus>CAN|Class2)\s+mode\s+\$06\s+data\b.*\.pdf$", re.IGNORECASE)
_DTC = re.compile(r"\b[PBCU][0-3][0-9A-F]{3}\b")
CODES_IN_TITLE = 4


def name_file(name: str, digest: str) -> DocId | None:
    """Which GM file `name` is: `17OBDG03 Engine Diagnostics.pdf` is `17OBDG03-engine`, and the misspelt
    `Transmisson` of two of GM's own file names is `transmission` too. `digest` is not needed: GM's names are
    unique per document."""
    found = _GROUP.match(name)
    if found:
        kind = found["kind"].lower()
        kind = "transmission" if kind.startswith("transmi") else kind
        doc = f"17OBDG{found['group']}-{kind}"
        return DocId(doc, doc, f"GM 17OBDG{found['group']} {kind.title()} Diagnostics", "2017 OBD parameter file")
    if _SUMMARY.match(name):
        return DocId(
            "2017-group-summary",
            "2017-group-summary",
            "GM 2017 OBD Group Summary",
            "vehicle to parameter file matrix",
        )
    found = _MODE6.match(name)
    if found:
        bus = found["bus"].lower()
        label = "GM Mode $06 CAN (GMLAN)" if bus == "can" else "GM Mode $06 Class2 (J1850)"
        return DocId(f"mode6-{bus}", f"mode6-{bus}", label, "Mode $06 data definitions")
    return None


def page_title(first: int, last: int, lines: list[str]) -> str:
    """A parameter page is named by the fault codes it carries (`P0010, P0011`); a page with none (a supporting
    table, a continuation) falls back to the first line of text."""
    codes = list(dict.fromkeys(m[0] for line in lines for m in _DTC.finditer(line)))
    if not codes:
        return ""
    shown = ", ".join(codes[:CODES_IN_TITLE])
    return shown + (f" (+{len(codes) - CODES_IN_TITLE})" if len(codes) > CODES_IN_TITLE else "")


SPEC = LocalPdfSpec(
    name="gm",
    title="GM OBD parameter files",
    terms=TERMS,
    name_file=name_file,
    instructions=(
        "GM 2017 OBD diagnostic parameter files and Mode $06 definitions, from the user's own copies of the PDFs. "
        "They are tables: each page is one section `p<page>` (a table row's cells are on one line, separated by "
        "' | '), titled by the fault codes on it. Loop: gm_search('<words or a code such as P0010>') -> "
        "gm_read('<ref>'). Refs: 'gm:17OBDG01-hybrid§p12', '...§p12¶3' (from line 3 of that page). gm_docs lists "
        "what is imported. Every tool refuses until the owner has set PRIMARYSOURCE_GM_ACCEPT_TERMS; the error "
        "says what to do."
    ),
    ref_example="gm:17OBDG01-hybrid§p12¶3",
    unit=Unit.BLOCK,
    pages_per_section=1,
    page_title=page_title,
)

GM = Collection(
    name="gm",
    title="GM 2017 OBD diagnostic parameter files from the owner's own PDFs",
    prefix="gm_",
    unit=Unit.BLOCK,
    grammar=LocalRefs(SPEC),
    server="primarysource.gm.server:server",
    cli="primarysource.gm.cli:main",
    identify="primarysource.gm.identify:identify",
)
"""Refs: `gm:17OBDG01-hybrid§p12¶3`: the document (named from the file), the PDF page as `p12`, and `¶n`, the nth
text line of that page (a table row's cells are one line, separated by ` | `)."""

__all__ = ["GM", "SPEC", "TERMS"]
