"""Primary integers 20 through 28 assigned directly under joint-iso-itu-t.

Assignments are read from the X.660 clause index. Text from an example marker onward is not an assignment, and a
primary integer outside 20 through 28 is not a node of this module. The clause text is not stored.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.oid.library import x660_index
from primarysource.oid.tree import Node

_PARENT = "2"
_LOW = 20
_HIGH = 28

# A PDF line break often lands inside an identifier (`network- operator`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
# The arc directly under joint-iso-itu-t: the identifier in parentheses is that arc, not a descendant.
_BRACE = re.compile(
    r"joint-iso-itu-t\s*\(\s*2\s*\)\s+(?P<name>[a-z][a-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)",
    re.IGNORECASE,
)
_NOT_JOINT = r"(?:(?!joint-iso-itu-t\b).)"
_PROSE = re.compile(
    rf"joint-iso-itu-t\b{_NOT_JOINT}{{0,500}}?"
    rf"primary integer value of\s+(?P<number>\d+)"
    rf"(?P<middle>{_NOT_JOINT}{{0,400}}?)"
    rf"secondary identifier of\s+(?P<name>[a-z][a-z0-9-]*)",
    re.IGNORECASE | re.DOTALL,
)
_LABEL = re.compile(r'non-integer Unicode label of\s+"(?P<label>[^"]+)"', re.IGNORECASE)


def _remember(found: dict[int, Node], number_text: str, name: str, label: str | None, cite: str) -> None:
    number = int(number_text)
    if number < _LOW or number > _HIGH or number in found:
        return
    unicode = label.strip() if label else ""
    labels = (str(number), unicode) if unicode else (str(number),)
    found[number] = Node(
        oid=f"{_PARENT}.{number}",
        names=(name.lower(),),
        unicode_labels=labels,
        cite=cite,
        parent=_PARENT,
    )


def _from_clause(text: str, cite: str, found: dict[int, Node]) -> None:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    head = _EXAMPLE.split(flat, maxsplit=1)[0]
    pending: list[tuple[int, str, str, str | None]] = []
    for match in _BRACE.finditer(head):
        pending.append((match.start(), str(match["number"]), str(match["name"]), None))
    for match in _PROSE.finditer(head):
        label_match = _LABEL.search(str(match["middle"]))
        label = str(label_match["label"]) if label_match else None
        pending.append((match.start(), str(match["number"]), str(match["name"]), label))
    for _, number_text, name, label in sorted(pending, key=lambda item: item[0]):
        _remember(found, number_text, name, label, cite)


def children(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs 2.20 through 2.28 assigned under joint-iso-itu-t. No such assignment yields an empty tuple."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.5')",
            "primarysource itu index X.660",
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT section_id, body FROM sections ORDER BY section_id").fetchall()
    rec = path.stem.split("-", 1)[0]
    found: dict[int, Node] = {}
    for section_id, body in rows:
        if section_id and body:
            _from_clause(str(body), f"{rec}§{section_id}", found)
    return tuple(found[number] for number in sorted(found))
