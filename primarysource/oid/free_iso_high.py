"""OID arcs assigned by the high free ISO and joint ISO/IEC extracts.

An assignment is an object-identifier value, or a name(number) the clause allocates, outside an example.
A bibliographic mention and a dotted number in an example allocate nothing. Clause text is not stored.
Catalogue id 19759@2015 is read from the cover-year file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_DOCS: tuple[str, ...] = (
    "16166@2010",
    "16167@2011",
    "18015@2006",
    "18037@2008",
    "18053@2000",
    "18057@2004",
    "19759@2015",
    "19763-9@2015",
    "20943-1@2003",
    "20943-3@2004",
    "21000-1@2004",
    "21890@2001",
    "22216@2022",
    "22678@2019",
    "22767@2005",
    "23272@2011",
    "23360-1-6@2021",
    "24715@2006",
    "24718@2025",
    "25438@2006",
    "26905@2006",
    "26927@2011",
    "27560@2023",
    "29107-1@2010",
    "29108@2013",
    "29110-5-6-1@2015",
    "29110-5-6-2@2014",
    "29119-11@2020",
    "29138-2@2009",
    "29166@2011",
    "29181-1@2012",
)

# The catalogue year and the year printed on the cover are not the same file name.
_COVER_FILE = {"19759@2015": "19759_2016.json"}

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


def _filename(doc: str) -> str:
    cover = _COVER_FILE.get(doc)
    if cover is not None:
        return cover
    number, year = doc.rsplit("@", 1)
    return f"{number}_{year}.json"


def _section_id(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _sections(payload: dict[str, object]) -> tuple[tuple[str, str], ...]:
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
            "iso_docs",
            "primarysource iso import",
        )
    return directory


def _open(directory: Path) -> tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...]:
    """Catalogue id, the id stored in the file (the cite year), and that file's sections."""
    opened: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
    for doc in _DOCS:
        path = directory / _filename(doc)
        if not path.is_file():
            continue
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        cite_doc = doc
        sections: tuple[tuple[str, str], ...] = ()
        if isinstance(payload, dict):
            label = payload.get("doc")
            if isinstance(label, str) and label:
                cite_doc = label
            sections = _sections(payload)
        opened.append((doc, cite_doc, sections))
    return tuple(opened)


def covered(extracted: Path | None = None) -> tuple[str, ...]:
    """Catalogue ids whose extract files were opened, in slice order.

    `extracted` defaults to the ISO extracts. A missing directory is an error. A missing file is omitted.
    """
    return tuple(doc for doc, _cite, _sections in _open(_directory(extracted)))


def children(extracted: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned by the opened extracts. No assignment means an empty tuple.

    `extracted` defaults to the ISO extracts. A cite uses the id stored in the file, so the cover year
    of 19759 is the year in the ref. The same oid keeps the earliest cite.
    """
    found: dict[str, Node] = {}
    for _doc, cite_doc, sections in _open(_directory(extracted)):
        for section_id, text in sections:
            _take(text, f"iso:{cite_doc}§{section_id}", found)
    return tuple(sorted(found.values(), key=lambda node: _oid_key(node.oid)))
