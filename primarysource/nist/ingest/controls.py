"""Section splitter for NIST control catalogues printed as PDF (SP 800-53 and its relatives).

Control catalogues do not number their sections the way prose documents do. A control is written as its
identifier followed by an upper-case title (``AC-2 ACCOUNT MANAGEMENT``), and its enhancements are written
relative to the parent (``(1) ACCOUNT MANAGEMENT | AUTOMATED ...`` under ``AC-2``, which is ``ac-2.1``).
This splitter recognises both, keeps the first occurrence of each identifier (later ones are the appendix
summary tables), and accepts a control identifier only where it is anchored: at the start of a line, after a
run of spaces, or after the page header. Prose that mentions a control in capitals is not a heading. An enhancement heading may also be glued to
the end of the page header when it opens a page, and is accepted there for the same reason.

Where the text has a ``-1`` control, indexing starts at the first one. The worked example of a control's structure in the introduction
(Figure 1 prints AU-4 and its first enhancement) would otherwise take those two ids, and the real AU-4 would
then be dropped as a repeat.

Validated against the XML catalogue of SP 800-53 Rev 5 (see the -oscal entries): every identifier found is in
the catalogue, with no false positives.
"""

from __future__ import annotations

import re

from primarysource.nist.models import Section

_CONTROL = re.compile(r"([A-Z]{2})-(\d+)(?:\((\d+)\))?\s{1,6}([A-Z][A-Z ,;:\-/'—]{3,})")
_CHILD = re.compile(
    r"^(?:\s*|.*(?:doi\.org|NIST\.SP)\S*\s+)\((\d+)\)\s+([A-Z][A-Z ,;:\-/'—|&]{3,})"
)
_PAGE_HEADER = ("doi.org", "NIST.SP")


def _anchored(line: str, start: int) -> bool:
    before = line[:start]
    return (
        before.strip() == ""
        or before.endswith("   ")
        or any(h in before for h in _PAGE_HEADER)
    )


def _heading_at(line: str, parent: str | None) -> tuple[str, str, bool] | None:
    """Return (control id, title, is_parent) when ``line`` opens a control, else None."""
    for m in _CONTROL.finditer(line):
        if _anchored(line, m.start()):
            base = f"{m.group(1).lower()}-{m.group(2)}"
            if m.group(3):
                return f"{base}.{m.group(3)}", m.group(4).strip(), False
            return base, m.group(4).strip(), True
    child = _CHILD.match(line)
    if child and parent:
        return f"{parent}.{child.group(1)}", child.group(2).strip(), False
    return None


def split_control_sections(text: str) -> tuple[Section, ...]:
    """One Section per control or enhancement, in document order, each running to the next heading."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    found: list[tuple[int, str, str, bool]] = []
    parent: str | None = None
    for number, line in enumerate(lines, start=1):
        hit = _heading_at(line, parent)
        if hit is None:
            continue
        if hit[2]:
            parent = hit[0]
        found.append((number, *hit))
    first = next((i for i, f in enumerate(found) if f[3] and f[1].endswith("-1")), 0)
    heads: list[tuple[int, str, str]] = []
    seen: set[str] = set()
    for number, control_id, title, _ in found[first:]:
        if control_id not in seen:
            seen.add(control_id)
            heads.append((number, control_id, title))
    sections: list[Section] = []
    for index, (start, control_id, title) in enumerate(heads):
        end = heads[index + 1][0] - 1 if index + 1 < len(heads) else len(lines)
        sections.append(
            Section(id=control_id, heading=title, start_line=start, end_line=end)
        )
    return tuple(sections)
