"""Arcs assigned directly under joint-iso-itu-t whose primary integer is 40 or greater.

The numbers and names come from the owner's X.660 clause index. A `name(number)` followed by further
components is a longer value, not an assignment of the second arc. Text from an example marker onward
is not an assignment. This module stores neither the clause nor a copy of the arcs.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node

_PARENT = "2"
_MIN = 40

# A PDF line break often lands inside an identifier (`joint-iso- itu-t`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
# The whole value is joint-iso-itu-t plus one arc. Anything after that arc is a longer value.
_BRACE = re.compile(
    r"\{\s*joint-iso-itu-t\s*(?:\(\s*2\s*\))?\s+"
    r"(?P<name>[a-z][a-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)\s*\}"
)
_PROSE = re.compile(
    r"primary integer value of\s+(?P<number>\d+)\s+"
    r'(?:and a non-integer Unicode label of\s+"(?P<unicode>[^"]+)"\s+)?'
    r"and a secondary identifier of\s+(?P<name>[a-z][a-z0-9-]*)"
)


def _labels(number: str, unicode: str | None) -> tuple[str, ...]:
    if unicode:
        return (number, unicode)
    return (number,)


def _node(number: str, name: str, unicode: str | None, cite: str) -> Node:
    return Node(
        oid=f"{_PARENT}.{number}",
        names=(name,),
        unicode_labels=_labels(number, unicode),
        cite=cite,
        parent=_PARENT,
    )


def _from_clause(text: str, cite: str, seen: set[str]) -> list[Node]:
    """Late arcs assigned in one clause. `seen` drops an arc already taken from an earlier clause."""
    assignment = _EXAMPLE.split(text, maxsplit=1)[0]
    flat = _HYPHEN_BREAK.sub("-", " ".join(assignment.split()))
    found: list[tuple[str, str, str | None]] = []
    for match in _BRACE.finditer(flat):
        found.append((str(match["number"]), str(match["name"]), None))
    if "joint-iso-itu-t" in flat:
        for match in _PROSE.finditer(flat):
            unicode = match["unicode"]
            found.append((str(match["number"]), str(match["name"]), None if unicode is None else str(unicode)))
    nodes: list[Node] = []
    for number, name, unicode in found:
        if int(number) < _MIN:
            continue
        oid = f"{_PARENT}.{number}"
        if oid in seen:
            continue
        seen.add(oid)
        nodes.append(_node(number, name, unicode, cite))
    return nodes


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under joint-iso-itu-t with primary integer 40 or greater.

    `index` defaults to the newest X.660 clause index. No such assignment is an empty result.
    """
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.5.4')",
            "primarysource itu index X.660",
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections ORDER BY section_id").fetchall()
    rec = path.stem.split("-", 1)[0]
    seen: set[str] = set()
    nodes: list[Node] = []
    for section_id, body in rows:
        if not section_id or not body:
            continue
        nodes.extend(_from_clause(str(body), f"{rec}§{section_id}", seen))
    return tuple(sorted(nodes, key=lambda node: int(node.oid.rsplit(".", 1)[1])))
