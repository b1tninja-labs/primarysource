"""Arcs assigned directly under ds (2.5).

An assignment is an object-identifier value of exactly one arc under ds. A longer value names a descendant.
When the same number is assigned again, the first cite stays and the names are united. A name defined as
another of those arcs is a further name of that arc. Text from an example marker onward is not an
assignment, and an assignment written as a comment is not one either. Clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import itu_home
from primarysource.oid.tree import Node

_PARENT = "2.5"
_X501 = "X.501-2019-10.sqlite3"
_X509 = "X.509-2019-10.sqlite3"

# A PDF line break often lands inside an identifier (`service- Element`). Join that before reading names.
# A comment marker is a hyphen that does not sit between identifier characters, and this pattern leaves it.
_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-z0-9])-\s+(?=[A-Za-z0-9])")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
# The closing brace ends the value. A further component means this arc was used, not assigned.
_DIRECT = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\s+(?:ID|OBJECT\s+IDENTIFIER)\s*::=\s*"
    r"\{\s*ds(?:\s*\(\s*5\s*\))?\s+"
    r"(?:(?P<inner>[A-Za-z][A-Za-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)|(?P<bare>\d+))\s*\}"
)
# A bare name after ::= is another name of an arc already collected. A following "(" is a different value.
_ALIAS = re.compile(
    r"(?P<alias>[A-Za-z][A-Za-z0-9-]*)\s+(?:ID|OBJECT\s+IDENTIFIER)\s*::=\s*"
    r"(?P<target>[A-Za-z][A-Za-z0-9-]*)\b(?!\s*\()"
)


def _missing(path: Path) -> LibError:
    return LibError(
        f"X.501 index not found: {path}",
        "itu_read('X.501§31.1.9')",
        "primarysource itu index X.501",
    )


def _sources(index: Path | None) -> tuple[Path, ...]:
    if index is not None:
        if not index.is_file():
            raise _missing(index)
        return (index,)
    directory = itu_home() / "index"
    x501 = directory / _X501
    if not x501.is_file():
        raise _missing(x501)
    paths = [x501]
    x509 = directory / _X509
    if x509.is_file():
        paths.append(x509)
    return tuple(paths)


def _prepare(body: str) -> str:
    flat = _HYPHEN_BREAK.sub("-", " ".join(body.split()))
    return _EXAMPLE.split(flat, maxsplit=1)[0]


def _commented(text: str, start: int) -> bool:
    index = start
    while index > 0 and text[index - 1].isspace():
        index -= 1
    return text[index - 2 : index] == "--"


def _clauses(path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections ORDER BY section_id").fetchall()
    rec = path.stem.split("-", 1)[0]
    found: list[tuple[str, str]] = []
    for section_id, body in rows:
        if not section_id or not body:
            continue
        found.append((f"{rec}§{section_id}", _prepare(str(body))))
    return found


def _pair(left: str, inner: str | None) -> tuple[str, ...]:
    if inner is None or inner == left:
        return (left,)
    return (left, inner)


def _store(found: dict[int, Node], number: int, names: tuple[str, ...], cite: str) -> None:
    current = found.get(number)
    if current is None:
        found[number] = Node(
            oid=f"{_PARENT}.{number}",
            parent=_PARENT,
            names=names,
            unicode_labels=(str(number),),
            cite=cite,
        )
        return
    merged = list(current.names)
    for name in names:
        if name not in merged:
            merged.append(name)
    if tuple(merged) == current.names:
        return
    found[number] = Node(
        oid=current.oid,
        parent=_PARENT,
        names=tuple(merged),
        unicode_labels=current.unicode_labels,
        cite=current.cite,
    )


def _take_direct(text: str, cite: str, found: dict[int, Node]) -> None:
    for match in _DIRECT.finditer(text):
        if _commented(text, match.start()):
            continue
        raw = match.group("bare") or match.group("number")
        name = match.group("name")
        if raw is None or name is None:
            continue
        inner = match.group("inner")
        _store(found, int(raw), _pair(name, inner), cite)


def _take_alias(text: str, found: dict[int, Node], lookup: dict[str, int]) -> None:
    for match in _ALIAS.finditer(text):
        if _commented(text, match.start()):
            continue
        alias = match.group("alias")
        target = match.group("target")
        if alias is None or target is None:
            continue
        number = lookup.get(target)
        if number is None:
            continue
        _store(found, number, (alias,), found[number].cite)


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned directly under 2.5.

    `index` defaults to the X.501 (2019-10) clause index. The X.509 (2019-10) index in the same directory
    is read as well when that file is present. No such assignment is an empty tuple.
    """
    clauses: list[tuple[str, str]] = []
    for path in _sources(index):
        clauses.extend(_clauses(path))
    found: dict[int, Node] = {}
    for cite, text in clauses:
        _take_direct(text, cite, found)
    lookup = {name: number for number, node in found.items() for name in node.names}
    for _, text in clauses:
        _take_alias(text, found, lookup)
    return tuple(found[number] for number in sorted(found))
