"""Operation and module arcs from X.511 that sit more than one level under 2.5.

An assignment is an `OBJECT IDENTIFIER` value or the object identifier on an ASN.1 module. Text from an
example marker onward is not an assignment, and a section titled as an example is not one either. An arc
whose parent is exactly 2.5 is left out. Operation information objects in this edition name an imported
code; they are not object identifier assignments. The clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

# Root arcs written by name when the value omits the number. These are not arcs assigned by X.511.
_ROOTS = {"itu-t": "0", "ccitt": "0", "iso": "1", "joint-iso-itu-t": "2"}
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?P<module>[A-Za-z][A-Za-z0-9-]*)\s*\{(?P<modbody>[^{}]*)\}\s*DEFINITIONS"
    r"|(?P<name>[A-Za-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*\{(?P<body>[^{}]*)\}"
)
_COMPONENT = re.compile(
    r"(?P<named>[A-Za-z][A-Za-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)"
    r"|(?P<bare>[A-Za-z][A-Za-z0-9-]*)"
    r"|(?P<digits>\d+)"
)


def _default_index() -> Path:
    found = sorted((collection_home("itu") / "index").glob("X.511-*.sqlite3"))
    if not found:
        raise LibError(
            "X.511 is not indexed",
            "itu_read('X.511§15.4')",
            "primarysource itu index X.511",
        )
    return found[-1]


def _components(body: str, known: dict[str, str]) -> list[str] | None:
    """Numbers along an object identifier value. An unknown bare name is not an arc of this text."""
    parts: list[str] = []
    pos = 0
    length = len(body)
    while pos < length:
        while pos < length and body[pos].isspace():
            pos += 1
        if pos >= length:
            break
        match = _COMPONENT.match(body, pos)
        if match is None:
            return None
        named, number, bare, digits = (
            match.group("named"),
            match.group("number"),
            match.group("bare"),
            match.group("digits"),
        )
        if named is not None and number is not None:
            parts.append(number)
        elif digits is not None:
            parts.append(digits)
        elif bare is not None:
            earlier = known.get(bare)
            if earlier is not None:
                parts.extend(earlier.split("."))
            elif bare in _ROOTS:
                parts.append(_ROOTS[bare])
            else:
                return None
        else:
            return None
        pos = match.end()
    if not parts:
        return None
    return parts


def _deeper(oid: str, parent: str | None) -> bool:
    """True when `oid` is under 2.5 and its parent is not exactly that arc."""
    if parent == "2.5":
        return False
    parts = oid.split(".")
    return len(parts) >= 4 and parts[0] == "2" and parts[1] == "5"


def _from_clause(text: str, cite: str, known: dict[str, str], nodes: list[Node], seen: set[str]) -> None:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    assignment = _EXAMPLE.split(flat, maxsplit=1)[0]
    for match in _ASSIGNMENT.finditer(assignment):
        module = match.group("module")
        name = module if module is not None else match.group("name")
        body = match.group("modbody") if module is not None else match.group("body")
        if name is None or body is None:
            continue
        parts = _components(body, known)
        if parts is None:
            continue
        oid = ".".join(parts)
        parent = ".".join(parts[:-1]) if len(parts) > 1 else None
        known[name] = oid
        if oid in seen or not _deeper(oid, parent):
            continue
        seen.add(oid)
        nodes.append(Node(oid=oid, parent=parent, names=(name,), unicode_labels=(), cite=cite))


def _sections(path: Path) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(sections)")}
        if "title" in columns:
            rows = connection.execute("SELECT section_id, body, title FROM sections ORDER BY rowid").fetchall()
        else:
            rows = connection.execute("SELECT section_id, body, '' FROM sections ORDER BY rowid").fetchall()
    for row in rows:
        section_id, body, title = row[0], row[1], row[2]
        if not isinstance(section_id, str) or not isinstance(body, str) or not body.strip():
            continue
        if isinstance(title, str) and "example" in title.casefold():
            continue
        found.append((section_id, body))
    return found


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Module arcs under 2.5 whose parent is not 2.5. `index` defaults to the newest X.511 clause index.

    An empty tuple means every assignment was a direct child of 2.5, or the text assigned none.
    """
    path = _default_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.511 index not found: {path}",
            "itu_read('X.511§15.4')",
            "primarysource itu index X.511",
        )
    rec = path.stem.split("-", 1)[0]
    known: dict[str, str] = {}
    nodes: list[Node] = []
    seen: set[str] = set()
    for section_id, body in _sections(path):
        _from_clause(body, f"{rec}§{section_id}", known, nodes, seen)
    return tuple(sorted(nodes, key=lambda node: _oid_key(node.oid)))
