"""Certificate-extension arcs one level under id-ce, from the X.509 (2019-10) clause index.

An assignment has the form `name OBJECT IDENTIFIER ::= {id-ce number}`. A further component is a deeper
arc. A name written immediately after `--` is a comment, and text from an example marker onward is
omitted. Two assignments of one number keep every distinct name and the earlier cite. Clause text is
not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_PARENT = "2.5.29"
_INDEX_NAME = "X.509-2019-10.sqlite3"

# A line-break hyphen (`id- ce`) joins. A comment marker (`-- name`) has two hyphens, so it stays.
_HYPHEN_BREAK = re.compile(r"(?<!-)-(?!-)\s+")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
# The name is a whole identifier. A suffix of `-- pinion` is still that comment, not a new name.
_ASSIGNED = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"(?<![-]{2})(?<![-]{2}\s)"
    r"(?P<name>[A-Za-z][A-Za-z0-9-]*)"
    r"\s+OBJECT\s+IDENTIFIER\s*::=\s*\{\s*id-ce\s+(?P<number>\d+)\s*\}"
)


def _default_index() -> Path:
    return collection_home("itu") / "index" / _INDEX_NAME


def _clause_key(section_id: str) -> tuple[tuple[int, str], ...]:
    parts: list[tuple[int, str]] = []
    for piece in section_id.split("."):
        if piece.isdigit():
            parts.append((0, f"{int(piece):08d}"))
        else:
            parts.append((1, piece))
    return tuple(parts)


def _remember(found: dict[str, Node], oid: str, name: str, cite: str) -> None:
    current = found.get(oid)
    if current is None:
        found[oid] = Node(oid=oid, parent=_PARENT, names=(name,), unicode_labels=(), cite=cite)
        return
    if name in current.names:
        return
    found[oid] = Node(
        oid=oid,
        parent=_PARENT,
        names=current.names + (name,),
        unicode_labels=(),
        cite=current.cite,
    )


def _take(text: str, cite: str, found: dict[str, Node]) -> None:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    assignment = _EXAMPLE.split(flat, maxsplit=1)[0]
    for match in _ASSIGNED.finditer(assignment):
        name = match.group("name")
        number = match.group("number")
        if name is None or number is None:
            continue
        _remember(found, f"{_PARENT}.{int(number)}", name, cite)


def _sections(path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        fetched = connection.execute("SELECT section_id, body FROM sections").fetchall()
    rows: list[tuple[str, str]] = []
    for section_id, body in fetched:
        if isinstance(section_id, str) and isinstance(body, str) and body.strip():
            rows.append((section_id, body))
    return rows


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under id-ce. `index` defaults to the X.509 (2019-10) clause index."""
    path = _default_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.509 index not found: {path}",
            "itu_read('X.509§A.2')",
            "primarysource itu index X.509#2019-10",
        )
    found: dict[str, Node] = {}
    rec = path.stem.split("-", 1)[0]
    for section_id, body in sorted(_sections(path), key=lambda item: _clause_key(item[0])):
        _take(body, f"{rec}§{section_id}", found)
    return tuple(sorted(found.values(), key=lambda node: int(node.oid.rsplit(".", 1)[1])))
