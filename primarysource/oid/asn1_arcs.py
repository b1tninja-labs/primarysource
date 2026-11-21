"""Arcs assigned under joint-iso-itu-t asn1(1), and that arc itself.

An assignment is an object-identifier value (`::=`), a module identifier (the value that introduces
`DEFINITIONS`), or a value introduced as assigned. Text from an example marker onward is not an
assignment. The arc 2.1 and one level beneath it are kept. The next arc is kept only when that same
value names it. Clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_RECS = ("X.680", "X.681", "X.682", "X.683")
_PARENT = "2"
_DEPTH = 2

# A PDF line break often lands inside an identifier (`joint- iso-itu-t`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
_VALUE = re.compile(
    r"\{\s*joint-iso-itu-t(?:\s*\(\s*2\s*\))?\s+"
    r"(?P<arc>[A-Za-z][A-Za-z0-9-]*)\s*\(\s*(?P<arc_number>\d+)\s*\)"
    r"(?P<rest>[^{}]*)\}",
    re.IGNORECASE,
)
_COMPONENT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*\(\s*(\d+)\s*\)|(\d+)")
_MODULE_TAIL = re.compile(r'\s*(?:"[^"]*"\s*)?DEFINITIONS\b', re.IGNORECASE)
_ASSIGNED = re.compile(r"\bassigned\b", re.IGNORECASE)
_IDENTIFIED = re.compile(r"\bidentified\b", re.IGNORECASE)


def _clause_key(section_id: str) -> tuple[tuple[int, str], ...]:
    parts: list[tuple[int, str]] = []
    for piece in section_id.split("."):
        if piece.isdigit():
            parts.append((0, f"{int(piece):08d}"))
        else:
            parts.append((1, piece))
    return tuple(parts)


def _oid_key(node: Node) -> tuple[int, ...]:
    return tuple(int(part) for part in node.oid.split("."))


def _remember(found: dict[str, Node], oid: str, parent: str, name: str, number: str, cite: str) -> None:
    if oid in found:
        return
    found[oid] = Node(
        oid=oid,
        parent=parent,
        names=(name,) if name else (),
        unicode_labels=(number,),
        cite=cite,
    )


def _is_assignment(flat: str, match: re.Match[str]) -> bool:
    before = flat[: match.start()]
    after = flat[match.end() :]
    if re.search(r"::=\s*$", before):
        return True
    if _MODULE_TAIL.match(after):
        return True
    assigned = list(_ASSIGNED.finditer(before))
    if not assigned:
        return False
    gap = before[assigned[-1].end() :]
    return "{" not in gap and _IDENTIFIED.search(gap) is None


def _components(rest: str) -> list[tuple[str, str]]:
    """At most the child and the grandchild. A later component is a longer value."""
    found: list[tuple[str, str]] = []
    for match in _COMPONENT.finditer(rest):
        name, number, bare = match.group(1), match.group(2), match.group(3)
        if bare is not None:
            found.append(("", str(int(bare))))
        elif name is not None and number is not None:
            found.append((name, str(int(number))))
        if len(found) == _DEPTH:
            break
    return found


def _from_clause(text: str, cite: str, found: dict[str, Node]) -> None:
    flat = _HYPHEN_BREAK.sub("-", " ".join(_EXAMPLE.split(text, maxsplit=1)[0].split()))
    for match in _VALUE.finditer(flat):
        arc = match.group("arc")
        arc_number = match.group("arc_number")
        rest = match.group("rest")
        if arc is None or arc_number is None or rest is None or arc.lower() != "asn1":
            continue
        if int(arc_number) != 1 or not _is_assignment(flat, match):
            continue
        number = str(int(arc_number))
        oid = f"{_PARENT}.{number}"
        _remember(found, oid, _PARENT, arc, number, cite)
        parent = oid
        for name, child_number in _components(rest):
            oid = f"{oid}.{child_number}"
            _remember(found, oid, parent, name, child_number, cite)
            parent = oid


def _read(path: Path, found: dict[str, Node]) -> None:
    rec = path.stem.split("-", 1)[0]
    try:
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT section_id, body FROM sections").fetchall()
    except sqlite3.Error as exc:
        raise LibError(
            f"ASN.1 index not found: {path}",
            "itu_read('X.680§D.2')",
            "primarysource itu index X.680",
        ) from exc
    sections: list[tuple[str, str]] = []
    for section_id, body in rows:
        if isinstance(section_id, str) and isinstance(body, str) and body.strip():
            sections.append((section_id, body))
    for section_id, body in sorted(sections, key=lambda item: _clause_key(item[0])):
        _from_clause(body, f"{rec}§{section_id}", found)


def _indexes(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        raise LibError(
            f"ASN.1 index not found: {directory}",
            "itu_read('X.680§D.2')",
            "primarysource itu index X.680",
        )
    chosen: list[Path] = []
    for rec in _RECS:
        found = sorted(directory.glob(f"{rec}-*.sqlite3"))
        if found:
            chosen.append(found[-1])
    if not chosen:
        raise LibError(
            f"ASN.1 index not found: {directory}",
            "itu_read('X.680§D.2')",
            "primarysource itu index X.680",
        )
    return tuple(chosen)


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs under joint-iso-itu-t asn1(1).

    `index` defaults to the ITU clause-index directory. Only the newest X.680, X.681, X.682, and
    X.683 index in that directory is read. No assignment is an empty result.
    """
    directory = collection_home("itu") / "index" if index is None else index
    found: dict[str, Node] = {}
    for path in _indexes(directory):
        _read(path, found)
    return tuple(sorted(found.values(), key=_oid_key))
