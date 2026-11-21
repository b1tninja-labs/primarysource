"""Encoding-rule arcs under joint-iso-itu-t from the 2021-02 indexes.

X.690 through X.697 are read. Each assigned value contributes one node per named arc, including the
parent arcs that value names. Text from an example marker onward is not an assignment, and a path
through a modules or examples arc is not an encoding-rule arc. Clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.itu.corpus import home
from primarysource.oid.tree import Node

_EDITION = "2021-02"
_RECS = ("X.690", "X.691", "X.692", "X.693", "X.694", "X.695", "X.696", "X.697")
_ROOT = "2"
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_COMPONENT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*\(\s*(\d+)\s*\)")
_VALUE = re.compile(
    r"\{\s*joint-iso-itu-t(?:\s*\(\s*2\s*\))?"
    r"(?P<body>(?:\s+[A-Za-z][A-Za-z0-9-]*\s*\(\s*\d+\s*\))*)"
    r"\s*\}"
    r'(?:\s*"(?P<iri>/[^"]*)")?',
    re.IGNORECASE,
)
# A modules arc identifies a module. An examples arc is a sketch. Neither is an encoding rule.
_NOT_ENCODING = frozenset({"modules", "examples"})


def _clause_key(section_id: str) -> tuple[tuple[int, str], ...]:
    parts: list[tuple[int, str]] = []
    for piece in section_id.split("."):
        if piece.isdigit():
            parts.append((0, f"{int(piece):08d}"))
        else:
            parts.append((1, piece))
    return tuple(parts)


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def _missing(path: Path) -> LibError:
    return LibError(
        f"X.690-{_EDITION} index not found: {path}",
        "itu_read('X.690§12.2')",
        f"primarysource itu index X.690#{_EDITION}",
    )


def _iri_labels(iri: str | None, count: int) -> tuple[str, ...] | None:
    if not iri:
        return None
    segments = tuple(segment for segment in iri.split("/") if segment)
    if len(segments) != count:
        return None
    return segments


def _from_clause(text: str, cite: str, found: dict[str, Node]) -> None:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    head = _EXAMPLE.split(flat, maxsplit=1)[0]
    if "assign" not in head.lower():
        return
    for match in _VALUE.finditer(head):
        body = match.group("body")
        if not body:
            continue
        parts = [(name.lower(), number) for name, number in _COMPONENT.findall(body)]
        if not parts or any(name in _NOT_ENCODING for name, _number in parts):
            continue
        labels = _iri_labels(match.group("iri"), len(parts))
        parent = _ROOT
        for index, (name, number) in enumerate(parts):
            oid = f"{parent}.{number}"
            if oid not in found:
                unicode = (number, labels[index]) if labels is not None else (number,)
                found[oid] = Node(
                    oid=oid,
                    parent=parent,
                    names=(name,),
                    unicode_labels=unicode,
                    cite=cite,
                )
            parent = oid


def _read(path: Path, found: dict[str, Node]) -> None:
    rec = path.stem.split("-", 1)[0]
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections").fetchall()
    sections: list[tuple[str, str]] = []
    for section_id, body in rows:
        if section_id and body:
            sections.append((str(section_id), str(body)))
    for section_id, body in sorted(sections, key=lambda item: _clause_key(item[0])):
        _from_clause(body, f"{rec}§{section_id}", found)


def _paths(index: Path | None) -> tuple[Path, ...]:
    if index is not None and not index.is_dir():
        if not index.is_file():
            raise _missing(index)
        return (index,)
    directory = home() / "index" if index is None else index
    anchor = directory / f"X.690-{_EDITION}.sqlite3"
    if not anchor.is_file():
        raise _missing(anchor)
    present = [anchor]
    for rec in _RECS[1:]:
        path = directory / f"{rec}-{_EDITION}.sqlite3"
        if path.is_file():
            present.append(path)
    return tuple(present)


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Encoding-rule arcs under 2.1 from the 2021-02 indexes.

    `index` is an index file, a directory of ``<Rec>-2021-02.sqlite3`` files, or None for the
    imported ITU index. A missing X.690 index is an error. A missing later index is skipped.
    No assignment yields an empty tuple.
    """
    found: dict[str, Node] = {}
    for path in _paths(index):
        _read(path, found)
    return tuple(sorted(found.values(), key=lambda node: _oid_key(node.oid)))
