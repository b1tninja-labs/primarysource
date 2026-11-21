"""Arcs 2.10 through 2.19 that a clause of X.660 assigns under joint-iso-itu-t.

The numbers and names come from the owner's ITU library. This module stores neither the clause nor a copy of
the arcs. A number in this range with no assigning clause is absent.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node

_LOW = 10
_HIGH = 19
_PARENT = "2"

# A PDF line break often lands inside an identifier (`joint- iso-itu-t`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
# Prose that allocates one arc beneath joint-iso-itu-t. A later table of arcs beneath that arc is a
# different parent, and this pattern does not match those rows.
_PROSE = re.compile(
    r"beneath joint-iso-itu-t\b.*?primary integer value of (?P<number>\d+)\s+"
    r'and a non-integer Unicode label of "(?P<unicode>[^"]+)"\s+'
    r"and a secondary identifier of (?P<name>[a-z][a-z0-9-]*)"
)
# An OBJECT IDENTIFIER value whose first component is joint-iso-itu-t(2). The following IRI, if any, is
# the non-integer Unicode label of that same arc.
_ASN = re.compile(r"joint-iso-itu-t\(2\)\s+(?P<name>[a-z][a-z0-9-]*)\((?P<number>\d+)\)")
_IRI = re.compile(r"/Joint-ISO-ITU-T/(?P<unicode>[^\"/\s]+)")


def _flatten(text: str) -> str:
    return _HYPHEN_BREAK.sub("-", " ".join(text.split()))


def _in_range(number: str) -> int | None:
    value = int(number)
    if _LOW <= value <= _HIGH:
        return value
    return None


def _add(nodes: list[Node], seen: set[str], number: int, name: str, label: str | None, cite: str) -> None:
    oid = f"{_PARENT}.{number}"
    if oid in seen:
        return
    seen.add(oid)
    labels = (str(number),) if label is None else (str(number), label)
    nodes.append(Node(oid=oid, parent=_PARENT, names=(name,), unicode_labels=labels, cite=cite))


def _from_clause(text: str, cite: str, nodes: list[Node], seen: set[str]) -> None:
    flat = _flatten(text)
    for match in _PROSE.finditer(flat):
        number = _in_range(str(match["number"]))
        if number is not None:
            _add(nodes, seen, number, str(match["name"]), str(match["unicode"]), cite)
    values = list(_ASN.finditer(flat))
    for index, match in enumerate(values):
        number = _in_range(str(match["number"]))
        if number is None:
            continue
        end = values[index + 1].start() if index + 1 < len(values) else len(flat)
        iri = _IRI.search(flat, match.end(), end)
        label = None if iri is None else str(iri["unicode"])
        _add(nodes, seen, number, str(match["name"]), label, cite)


def _load(path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections ORDER BY section_id").fetchall()
    return [(str(section_id), str(body)) for section_id, body in rows if section_id and body]


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs 2.10 through 2.19 assigned under joint-iso-itu-t. `index` defaults to the newest X.660 index."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.5')",
            "primarysource itu index X.660",
        )
    rec = path.stem.split("-", 1)[0]
    nodes: list[Node] = []
    seen: set[str] = set()
    for section_id, body in _load(path):
        _from_clause(body, f"{rec}§{section_id}", nodes, seen)
    return tuple(sorted(nodes, key=lambda node: int(node.oid.rsplit(".", 1)[1])))
