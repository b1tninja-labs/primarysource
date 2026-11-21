"""Arcs X.660 assigns directly under root arc 2.

Annex A.5 stores those arcs in two flattened shapes: a table with the same columns as the other root
arcs, and a prose assignment of one arc (a primary integer value, or a two-component name and number
under joint-iso-itu-t). Text from an example marker onward is not an assignment. A longer object
identifier is not a child of arc 2. The clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node, parse_root_table

_PARENT = "2"
_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"-\s+")
_NAME = re.compile(r"[a-z][a-z0-9-]*")
_NOT_A_NAME = frozenset({"see", "and"})
# One arc allocated under joint-iso-itu-t: number, non-integer label, secondary identifier.
_ALLOCATED = re.compile(
    r"joint-iso-itu-t\b"
    r"[^.]{0,900}?"
    r"primary integer value of\s+(?P<number>\d+)"
    r"[^.]{0,400}?"
    r'non-integer Unicode label of\s+"(?P<unicode>[^"]+)"'
    r"[^.]{0,300}?"
    r"secondary identifier of\s+(?P<name>[a-z][a-z0-9-]*)"
    r"(?:\s*\((?P<synonyms>[^)]*)\))?",
    re.IGNORECASE,
)
# A value whose second component is the direct child. A third component is a deeper arc.
_DIRECT_OID = re.compile(
    r"\{joint-iso-itu-t\(\s*2\s*\)\s+(?P<name>[a-z][a-z0-9-]*)\(\s*(?P<number>\d+)\s*\)\s*\}",
    re.IGNORECASE,
)
_DIRECT_IRI = re.compile(r'"/Joint-ISO-ITU-T/(?P<label>[^"/]+)"')


def _clause_key(section_id: str) -> tuple[tuple[int, str], ...]:
    parts: list[tuple[int, str]] = []
    for piece in section_id.split("."):
        if piece.isdigit():
            parts.append((0, f"{int(piece):08d}"))
        else:
            parts.append((1, piece))
    return tuple(parts)


def _names(primary: str, synonyms: str | None) -> tuple[str, ...]:
    names = [primary]
    if synonyms:
        for name in _NAME.findall(synonyms):
            if name not in names and name not in _NOT_A_NAME:
                names.append(name)
    return tuple(names)


def _table_nodes(assignment: str, cite: str) -> tuple[Node, ...]:
    """Rows of a direct-child table. `parse_root_table` raises when this clause has none."""
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


def _allocated(assignment: str, cite: str) -> tuple[Node, ...]:
    nodes: list[Node] = []
    for match in _ALLOCATED.finditer(assignment):
        number = match.group("number")
        name = match.group("name")
        label = match.group("unicode")
        if number is None or name is None or label is None:
            continue
        nodes.append(
            Node(
                oid=f"{_PARENT}.{number}",
                parent=_PARENT,
                names=_names(name, match.group("synonyms")),
                unicode_labels=(number, label),
                cite=cite,
            )
        )
    return tuple(nodes)


def _iri_label(assignment: str, end: int) -> str | None:
    window = assignment[end : end + 400]
    stop = window.find(". ")
    if stop != -1:
        window = window[:stop]
    found = _DIRECT_IRI.search(window)
    if found is None:
        return None
    return found.group("label")


def _oid_nodes(assignment: str, cite: str) -> tuple[Node, ...]:
    nodes: list[Node] = []
    for match in _DIRECT_OID.finditer(assignment):
        number = match.group("number")
        name = match.group("name")
        if number is None or name is None:
            continue
        label = _iri_label(assignment, match.end())
        labels = (number, label) if label else (number,)
        nodes.append(
            Node(
                oid=f"{_PARENT}.{number}",
                parent=_PARENT,
                names=(name,),
                unicode_labels=labels,
                cite=cite,
            )
        )
    return tuple(nodes)


def _from_clause(text: str, cite: str) -> tuple[Node, ...]:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    # Examples use the same name(number) spelling as assignments. Drop them before parsing.
    assignment = _EXAMPLE.split(flat, maxsplit=1)[0]
    return _table_nodes(assignment, cite) + _allocated(assignment, cite) + _oid_nodes(assignment, cite)


def _annex(path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        fetched = connection.execute(
            "SELECT section_id, body FROM sections WHERE section_id = 'A.5' OR section_id LIKE 'A.5.%'"
        ).fetchall()
    sections: list[tuple[str, str]] = []
    for section_id, body in fetched:
        if isinstance(section_id, str) and isinstance(body, str) and body.strip():
            sections.append((section_id, body))
    return sections


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under root arc 2. `index` defaults to the newest X.660 clause index."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.5')",
            "primarysource itu index X.660",
        )
    sections = _annex(path)
    if not sections:
        raise LibError(
            "X.660 has no clause A.5",
            "the joint-arc annex may have been stored under another clause id",
            "primarysource itu index X.660",
        )
    rec = path.stem.split("-", 1)[0]
    nodes: list[Node] = []
    seen: set[str] = set()
    for section_id, body in sorted(sections, key=lambda item: _clause_key(item[0])):
        for node in _from_clause(body, f"{rec}§{section_id}"):
            if node.oid in seen:
                continue
            seen.add(node.oid)
            nodes.append(node)
    if not nodes:
        raise LibError(
            "no arcs under 2 in the clause",
            "itu_read('X.660§A.5')",
            "primarysource itu index X.660",
        )
    return tuple(sorted(nodes, key=lambda node: int(node.oid.rsplit(".", 1)[1])))
