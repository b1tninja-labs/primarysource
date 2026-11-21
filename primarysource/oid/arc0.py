"""Arcs X.660 assigns directly under root arc 0.

The numbers and names come from the annex table in the owner's ITU library. This module stores neither the
clause nor a copy of the arcs. Illustrative ``name(number)`` values are not rows of that table.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node

_CLAUSE = "A.3.2"
_PARENT = "0"

# A PDF line break often lands inside an identifier (`network- operator`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
# Primary integer, quoted integer-valued label, then either a quoted non-integer label or a cross-reference
# in parentheses, then the secondary identifier. A parenthesis is not a Unicode label.
_ROW = re.compile(
    r'(?P<number>\d+)\s+"(?P<integer_label>[^"]+)"\s+'
    r'(?:"(?P<unicode>[^"]+)"|\([^)]*\))\s+'
    r"(?P<name>[a-z][a-z0-9-]*)"
)


def _assignments(text: str, cite: str) -> tuple[Node, ...]:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    nodes: list[Node] = []
    seen: set[str] = set()
    for match in _ROW.finditer(flat):
        number = str(match["number"])
        oid = f"{_PARENT}.{number}"
        if oid in seen:
            continue
        seen.add(oid)
        integer_label = str(match["integer_label"])
        unicode_label = match["unicode"]
        labels = (integer_label, str(unicode_label)) if unicode_label else (integer_label,)
        nodes.append(
            Node(
                oid=oid,
                names=(str(match["name"]),),
                unicode_labels=labels,
                cite=cite,
                parent=_PARENT,
            )
        )
    if not nodes:
        raise LibError(
            "no arcs under 0 in the clause",
            f"itu_read('X.660§{_CLAUSE}')",
            "primarysource itu index X.660",
        )
    return tuple(sorted(nodes, key=lambda node: int(node.oid.split(".")[-1])))


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under root arc 0. A ``name(number)`` illustration is not an arc."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            f"itu_read('X.660§{_CLAUSE}')",
            "primarysource itu index X.660",
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT body FROM sections WHERE section_id = ?", (_CLAUSE,)).fetchone()
    if row is None or not row[0]:
        raise LibError(
            f"X.660 has no clause {_CLAUSE}",
            "the annex table may have been stored under another clause id",
            "primarysource itu index X.660",
        )
    rec = path.stem.split("-", 1)[0]
    return _assignments(str(row[0]), f"{rec}§{_CLAUSE}")
