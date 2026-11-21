"""Arcs X.660 assigns directly under root arc 1.

The assignment is the annex table stored as clause A.4.2. A name with a parenthesized number is how an
example cites an arc; text from an example marker onward is not an assignment. The clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node, parse_root_table

_CLAUSE = "A.4.2"
_PARENT = "1"
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")


def parse_arc1_table(text: str, cite: str) -> tuple[Node, ...]:
    """Rows of the arc-1 table. Each oid is `1.` plus the primary integer value."""
    assignment = _EXAMPLE.split(text, maxsplit=1)[0]
    try:
        parsed = parse_root_table(assignment, cite)
    except LibError:
        raise LibError(
            "no arcs assigned under arc 1",
            f"itu_read('{cite}')",
            "primarysource itu index X.660",
        ) from None
    nodes = [
        Node(
            oid=f"{_PARENT}.{node.oid}",
            parent=_PARENT,
            names=node.names,
            unicode_labels=node.unicode_labels,
            cite=cite,
        )
        for node in parsed
    ]
    return tuple(sorted(nodes, key=lambda node: int(node.oid.rsplit(".", 1)[1])))


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under root arc 1. `index` defaults to the newest X.660 clause index."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.4.2')",
            "primarysource itu index X.660",
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT body FROM sections WHERE section_id = ?",
            (_CLAUSE,),
        ).fetchone()
    if row is None or not row[0]:
        raise LibError(
            f"X.660 has no clause {_CLAUSE}",
            "the ISO arc table may have been stored under another clause id",
            "primarysource itu index X.660",
        )
    rec = path.stem.split("-", 1)[0]
    return parse_arc1_table(str(row[0]), f"{rec}§{_CLAUSE}")
