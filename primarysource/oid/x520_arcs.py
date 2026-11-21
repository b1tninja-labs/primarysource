"""Attribute arcs assigned under the attribute-type arc.

`id-at` is that arc, dotted `2.5.4`. Each `name OBJECT IDENTIFIER ::= {id-at ...}` value under it is one
node, and `parent` is `2.5.4`. A direct child of `2.5` is not emitted. An identifier introduced by `--`,
and text from an example marker onward, is not an assignment. The same oid keeps one node and the names
seen for it. Clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_PARENT = "2.5.4"
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
_ASSIGNMENT = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*\{(?P<body>[^{}]*)\}")


def _flatten(text: str) -> str:
    return _HYPHEN_BREAK.sub("-", " ".join(text.split()))


def _commented(text: str, start: int) -> bool:
    """True when `--` introduces this identifier, which is how a module marks an arc it does not assign."""
    index = start
    while index > 0 and text[index - 1].isspace():
        index -= 1
    return index >= 2 and text[index - 2 : index] == "--"


def _numbers(body: str) -> tuple[str, ...] | None:
    parts = body.split()
    if len(parts) < 2 or parts[0] != "id-at":
        return None
    numbers = parts[1:]
    if any(not number.isdigit() for number in numbers):
        return None
    return tuple(numbers)


def _ds_child(oid: str) -> bool:
    parts = oid.split(".")
    return len(parts) == 3 and parts[0] == "2" and parts[1] == "5"


def _add(found: dict[str, Node], oid: str, name: str, cite: str) -> None:
    current = found.get(oid)
    if current is None:
        found[oid] = Node(oid=oid, parent=_PARENT, names=(name,), unicode_labels=(), cite=cite)
        return
    if name in current.names:
        return
    found[oid] = Node(
        oid=current.oid,
        parent=current.parent,
        names=current.names + (name,),
        unicode_labels=(),
        cite=current.cite,
    )


def _take(text: str, cite: str, found: dict[str, Node]) -> None:
    assignment = _EXAMPLE.split(_flatten(text), maxsplit=1)[0]
    for match in _ASSIGNMENT.finditer(assignment):
        if _commented(assignment, match.start()):
            continue
        numbers = _numbers(match.group("body"))
        if numbers is None:
            continue
        oid = _PARENT + "." + ".".join(numbers)
        if _ds_child(oid):
            continue
        _add(found, oid, match.group("name"), cite)


def _sections(path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections ORDER BY rowid").fetchall()
    sections: list[tuple[str, str]] = []
    for section_id, body in rows:
        if isinstance(section_id, str) and isinstance(body, str) and body.strip():
            sections.append((section_id, body))
    return sections


def _index(index: Path | None) -> Path:
    if index is None:
        found = sorted((collection_home("itu") / "index").glob("X.520-*.sqlite3"))
        if not found:
            raise LibError(
                "X.520 is not indexed",
                "itu_read('X.520')",
                "primarysource itu fetch X.520 && primarysource itu index X.520",
            )
        return found[-1]
    if not index.is_file():
        raise LibError(
            f"X.520 index not found: {index}",
            "itu_read('X.520')",
            "primarysource itu index X.520",
        )
    return index


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Attribute arcs assigned under `2.5.4`.

    `index` defaults to the newest X.520 clause index. One node per oid; names on a repeated oid are united.
    """
    path = _index(index)
    rec = path.stem.split("-", 1)[0]
    found: dict[str, Node] = {}
    for section_id, body in _sections(path):
        _take(body, f"{rec}§{section_id}", found)
    return tuple(sorted(found.values(), key=lambda node: tuple(int(part) for part in node.oid.split("."))))
