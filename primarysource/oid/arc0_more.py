"""Direct children of root arc 0 assigned outside the A.3.2 table.

Clauses A.3.3 through A.3.9 and A.6 are read from the owner's ITU library. This module stores neither those
clauses nor a copy of the arcs. A table row is an assignment. A parenthesized number and text from an example
marker onward are not.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node

_PARENT = "0"
_SCOPE_SQL = """
SELECT section_id, body FROM sections
WHERE section_id LIKE 'A.3.%' OR section_id = 'A.6' OR section_id LIKE 'A.6.%'
"""

# A PDF line break often lands inside an identifier (`sprocket- washer`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\bexample\b", re.IGNORECASE)
_SAMPLE = re.compile(r"\{[^{}]*\}")
# Primary integer, quoted integer-valued label, then either a quoted non-integer label or a cross-reference
# in parentheses, then the secondary identifier. A parenthesis is not a Unicode label.
_ROW = re.compile(
    r'(?P<number>\d+)\s+"(?P<integer_label>[^"]+)"\s+'
    r'(?:"(?P<unicode>[^"]+)"|\([^)]*\))\s+'
    r"(?P<name>[a-z][a-z0-9-]*)"
)


def _in_scope(section_id: str) -> bool:
    """A.3.3 through A.3.9, including their subclauses, and A.6 with its subclauses."""
    if section_id == "A.6" or section_id.startswith("A.6."):
        return True
    if not section_id.startswith("A.3."):
        return False
    head = section_id.removeprefix("A.3.").split(".", 1)[0]
    return head.isdigit() and 3 <= int(head) <= 9


def _clause_key(section_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in section_id.removeprefix("A.").split("."))


def _assignments(text: str, cite: str) -> tuple[Node, ...]:
    kept = _EXAMPLE.split(text, maxsplit=1)[0]
    flat = _HYPHEN_BREAK.sub("-", " ".join(_SAMPLE.sub(" ", kept).split()))
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
    return tuple(nodes)


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under root arc 0 by A.3.3–A.3.9 or A.6.

    A ``name(number)`` sample is not an arc. The A.3.2 table is not read.
    """
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.3.3')",
            "primarysource itu index X.660",
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        fetched = connection.execute(_SCOPE_SQL).fetchall()
    chosen = [(str(section_id), body) for section_id, body in fetched if _in_scope(str(section_id))]
    if not chosen:
        raise LibError(
            "X.660 has no clauses A.3.3 through A.3.9 or A.6",
            "itu_read('X.660§A.3.3')",
            "primarysource itu index X.660",
        )
    rec = path.stem.split("-", 1)[0]
    nodes: list[Node] = []
    seen: set[str] = set()
    for section_id, body in sorted(chosen, key=lambda item: _clause_key(str(item[0]))):
        if not body:
            continue
        for node in _assignments(str(body), f"{rec}§{section_id}"):
            if node.oid in seen:
                continue
            seen.add(node.oid)
            nodes.append(node)
    return tuple(sorted(nodes, key=lambda node: int(node.oid.rsplit(".", 1)[1])))
