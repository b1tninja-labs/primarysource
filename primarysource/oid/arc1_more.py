"""Direct children of root arc 1 assigned outside clause A.4.2.

Rows come from A.4.3, A.4.4, A.4.5, A.4.6, A.4.7, and A.6 (A.6.1 through A.6.4 when the heading has no body).
A row is a primary integer, two quoted labels, and a secondary identifier. Text from an example marker onward
is not a row. No such row means no arc. The clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node, parse_root_table

_CLAUSES = ("A.4.3", "A.4.4", "A.4.5", "A.4.6", "A.4.7", "A.6", "A.6.1", "A.6.2", "A.6.3", "A.6.4")
_PARENT = "1"
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")


def _rows(text: str, cite: str) -> tuple[Node, ...]:
    """Assignment rows in one clause. An example, or a clause with no row, contributes nothing."""
    assignment = _EXAMPLE.split(text, maxsplit=1)[0]
    try:
        parsed = parse_root_table(assignment, cite)
    except LibError:
        return ()
    return tuple(
        Node(
            oid=f"{_PARENT}.{node.oid}",
            parent=_PARENT,
            names=node.names,
            unicode_labels=node.unicode_labels,
            cite=cite,
        )
        for node in parsed
    )


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under root arc 1 in A.4.3–A.4.7 and A.6. No row means an empty result."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.4.3')",
            "primarysource itu index X.660",
        )
    nodes: list[Node] = []
    seen: set[str] = set()
    rec = path.stem.split("-", 1)[0]
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        for clause in _CLAUSES:
            row = connection.execute(
                "SELECT body FROM sections WHERE section_id = ?",
                (clause,),
            ).fetchone()
            if row is None or not row[0]:
                continue
            for node in _rows(str(row[0]), f"{rec}§{clause}"):
                if node.oid in seen:
                    continue
                seen.add(node.oid)
                nodes.append(node)
    return tuple(sorted(nodes, key=lambda node: int(node.oid.rsplit(".", 1)[1])))
