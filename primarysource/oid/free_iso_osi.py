"""OID arcs assigned by the free OSI extracts and the joint registration text.

An assignment is an object-identifier value, or a name and number the clause allocates, outside an example.
A bibliographic mention and a dotted number in an example allocate nothing. Clause text is not stored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_DOCS: tuple[str, ...] = (
    "7498-1@1994",
    "7498-3@1997",
    "7498-4@1989",
    "7501-1@2008",
    "7501-2@1997",
    "7501-3@2005",
    "8072@1996",
    "8073@1997",
    "8208@2000",
    "8348@2002",
    "8473-1@1998",
    "8473-2@1996",
    "8473-3@1995",
    "8473-4@1995",
    "8473-5@1997",
    "8602@1995",
    "8632-1@1999",
    "8632-3@1999",
    "8632-4@1999",
    "8663@2025",
    "8878@1992",
    "9075-1@2023",
    "9577@1999",
    "9834-9@2008",
)

# A PDF line break often lands inside an identifier (`joint- iso-itu-t`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_SIGNAL = re.compile(
    r"assign|allocat|object\s+identifiers?|::=|\bOID\s+arc\b",
    re.IGNORECASE,
)
_ROOTS = {
    "itu-t": "0",
    "ccitt": "0",
    "iso": "1",
    "joint-iso-itu-t": "2",
    "joint-iso-ccitt": "2",
}
_VALUE = re.compile(
    r"\{\s*"
    r"(?P<root>joint-iso-itu-t|joint-iso-ccitt|itu-t|ccitt|iso)"
    r"(?:\s*\(\s*(?P<number>\d+)\s*\))?"
    r"(?P<body>(?:\s+[A-Za-z][A-Za-z0-9-]*\s*\(\s*\d+\s*\))+)"
    r"[^{}]*\}",
    re.IGNORECASE,
)
_COMPONENT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*\(\s*(\d+)\s*\)")
_SYNONYM = re.compile(
    r"secondary\s+identifier\s+([A-Za-z][A-Za-z0-9-]*)\s+is\s+a\s+synonym\s+for\s+([A-Za-z][A-Za-z0-9-]*)",
    re.IGNORECASE,
)


def _flatten(text: str) -> str:
    return _HYPHEN_BREAK.sub("-", " ".join(text.split()))


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(part) for part in oid.split("."))


def _remember(found: dict[str, Node], oid: str, parent: str, name: str, number: str, cite: str) -> None:
    current = found.get(oid)
    if current is None:
        found[oid] = Node(
            oid=oid,
            parent=parent,
            names=(name,),
            unicode_labels=(number,),
            cite=cite,
        )
        return
    if name in current.names:
        return
    found[oid] = Node(
        oid=current.oid,
        parent=current.parent,
        names=current.names + (name,),
        unicode_labels=current.unicode_labels,
        cite=current.cite,
    )


def parse_assignments(text: str, cite: str) -> tuple[Node, ...]:
    """Arcs `text` allocates. `cite` is stored on each new node. The text is not."""
    found: dict[str, Node] = {}
    _take(text, cite, found)
    return tuple(sorted(found.values(), key=lambda node: _oid_key(node.oid)))


def _take(text: str, cite: str, found: dict[str, Node]) -> None:
    head = _EXAMPLE.split(_flatten(text), maxsplit=1)[0]
    if _SIGNAL.search(head) is None:
        return
    for match in _VALUE.finditer(head):
        root = match.group("root")
        if root is None:
            continue
        number = match.group("number") or _ROOTS.get(root.lower())
        body = match.group("body")
        if number is None or body is None:
            continue
        parent = number
        for name, arc in _COMPONENT.findall(body):
            oid = f"{parent}.{arc}"
            _remember(found, oid, parent, name, arc, cite)
            parent = oid
    for synonym in _SYNONYM.finditer(head):
        extra, primary = synonym.group(1), synonym.group(2)
        for node in list(found.values()):
            if primary not in node.names or extra in node.names or not node.unicode_labels:
                continue
            _remember(found, node.oid, node.parent or "", extra, node.unicode_labels[0], node.cite)


def _filename(doc: str) -> str:
    number, year = doc.rsplit("@", 1)
    return f"{number}_{year}.json"


def _section_id(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _sections(payload: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(payload, dict):
        return ()
    raw = payload.get("sections")
    if not isinstance(raw, list):
        return ()
    found: list[tuple[str, str]] = []
    for section in raw:
        if not isinstance(section, dict):
            continue
        section_id = _section_id(section.get("id"))
        text = section.get("text")
        if section_id is None or not isinstance(text, str) or not text:
            continue
        found.append((section_id, text))
    return tuple(found)


def _directory(extracted: Path | None) -> Path:
    directory = collection_home("iso") / "extracted" if extracted is None else extracted
    if not directory.is_dir():
        raise LibError(
            f"ISO extract not found: {directory}",
            "iso_read('9834-9@2008§introduction')",
            "primarysource iso import",
        )
    return directory


def _open(directory: Path) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    opened: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for doc in _DOCS:
        path = directory / _filename(doc)
        if not path.is_file():
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        opened.append((doc, _sections(payload)))
    return tuple(opened)


def covered(extracted: Path | None = None) -> tuple[str, ...]:
    """Doc ids whose extract files were opened, in slice order.

    `extracted` defaults to the ISO extracts. A missing directory is an error. A missing file is omitted.
    """
    return tuple(doc for doc, _sections in _open(_directory(extracted)))


def children(extracted: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned by the opened extracts. No assignment means an empty tuple.

    `extracted` defaults to the ISO extracts. The same oid keeps the earliest cite and every name seen for it.
    """
    found: dict[str, Node] = {}
    for doc, sections in _open(_directory(extracted)):
        for section_id, text in sections:
            _take(text, f"iso:{doc}§{section_id}", found)
    return tuple(sorted(found.values(), key=lambda node: _oid_key(node.oid)))
