"""Arcs assigned directly under joint-iso-itu-t with primary integers 0 through 9.

An assignment is an object-identifier value of exactly that one arc. A longer value names a descendant. When two
index files assign the same number, the earliest file name supplies the cite. Clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node

_PARENT = "2"
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
# The closing brace ends the value. A further component means this arc was used, not assigned.
_ASSIGNED = re.compile(
    r"::=\s*\{\s*joint-iso-itu-t(?:\s*\(\s*2\s*\))?\s+"
    r"(?P<name>[a-z][a-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)\s*\}"
)


def _take(text: str, cite: str, found: dict[str, Node]) -> None:
    assignment = _EXAMPLE.split(text, maxsplit=1)[0]
    flat = _HYPHEN_BREAK.sub("-", " ".join(assignment.split()))
    for match in _ASSIGNED.finditer(flat):
        number = int(match["number"])
        if number > 9:
            continue
        oid = f"{_PARENT}.{number}"
        if oid in found:
            continue
        found[oid] = Node(
            oid=oid,
            parent=_PARENT,
            names=(str(match["name"]),),
            unicode_labels=(str(number),),
            cite=cite,
        )


def _read(path: Path, found: dict[str, Node]) -> None:
    rec = path.stem.split("-", 1)[0]
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections").fetchall()
    for row in rows:
        body = row[1]
        if not body:
            continue
        _take(str(body), f"{rec}§{row[0]}", found)


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs 2.0 through 2.9.

    `index` defaults to the newest X.660 clause index. Every index file in that directory is read.
    """
    if index is None:
        anchor = x660_index()
    elif not index.is_file():
        raise LibError(
            f"X.660 index not found: {index}",
            "itu_read('X.660§A.5.1')",
            "primarysource itu index X.660",
        )
    else:
        anchor = index
    found: dict[str, Node] = {}
    for path in sorted(anchor.parent.glob("*.sqlite3")):
        _read(path, found)
    return tuple(sorted(found.values(), key=lambda node: int(node.oid.rsplit(".", 1)[1])))
