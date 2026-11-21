"""OID arcs assigned by one batch of free ISO and joint ISO/IEC documents.

An assignment is an OBJECT IDENTIFIER value, or a name(number) the clause allocates. A bibliographic
mention of ITU-T, and a dotted number in an example, are not assignments. A document that assigns
nothing is still covered. Clause text is not stored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_DOCS: tuple[str, ...] = (
    "10000-1@1998",
    "10000-2@1998",
    "10000-3@1998",
    "10032@2003",
    "10090@1992",
    "10149@1995",
    "10176@2003",
    "10182@2016",
    "10822-1@2025",
    "11017@1998",
    "11172-5@1998",
    "12785-3@2012",
    "12860@2009",
    "12861@2009",
    "13818-5@2005",
    "14369@2018",
    "14475@2001",
    "15938-11@2005",
    "15942@2000",
    "15944-6@2015",
)

_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_HYPHEN_BREAK = re.compile(r"-\s+")
_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9-])([A-Za-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*\{([^{}]*)\}")
_COMPONENT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*\(\s*(\d+)\s*\)|([A-Za-z][A-Za-z0-9-]*)|(\d+)")
_FORM = "an assignment has the form name OBJECT IDENTIFIER ::= { parent name(number) }"


def _filename(doc: str) -> str:
    return f"{doc.replace('@', '_')}.json"


def _extracted() -> Path:
    path = collection_home("iso") / "extracted"
    if path.is_dir():
        return path
    raise LibError(
        f"ISO extract directory not found: {path}",
        "iso_docs",
        "primarysource iso import",
    )


def _skip(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _components(body: str, known: dict[str, str]) -> list[str]:
    """Numbers along `{ parent name(number) }`. A bare name must already have been assigned."""
    parts: list[str] = []
    pos = _skip(body, 0)
    while pos < len(body):
        match = _COMPONENT.match(body, pos)
        if match is None:
            raise LibError("a component is not a name, a name(number), or a number", _FORM)
        named, number, bare, digits = match.group(1), match.group(2), match.group(3), match.group(4)
        if named is not None and number is not None:
            parts.append(number)
        elif digits is not None:
            parts.append(digits)
        elif bare is not None:
            oid = known.get(bare)
            if oid is None:
                raise LibError(
                    f"no value for {bare}",
                    "write name(number), or assign that name earlier in the fragment",
                )
            parts.extend(oid.split("."))
        else:
            raise LibError("a component is not a name, a name(number), or a number", _FORM)
        pos = _skip(body, match.end())
    return parts


def parse_assignments(text: str, cite: str) -> tuple[Node, ...]:
    """Nodes for each OBJECT IDENTIFIER assignment before an example marker.

    A name(number) in the braces is one step of the path. The name on the left is the arc being
    assigned. A bibliographic mention and a dotted number in an example assign nothing. `cite` is
    stored on every node. The text is not.
    """
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    assignment = _EXAMPLE.split(flat, maxsplit=1)[0]
    known: dict[str, str] = {}
    nodes: list[Node] = []
    for match in _ASSIGNMENT.finditer(assignment):
        name, body = match.group(1), match.group(2)
        parts = _components(body, known)
        if not parts:
            continue
        oid = ".".join(parts)
        parent = ".".join(parts[:-1]) if len(parts) > 1 else None
        known[name] = oid
        nodes.append(Node(oid=oid, names=(name,), unicode_labels=(), cite=cite, parent=parent))
    return tuple(nodes)


def _sections(path: Path) -> tuple[tuple[str, str], ...]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return ()
    sections = loaded.get("sections")
    if not isinstance(sections, list):
        return ()
    rows: list[tuple[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_id = section.get("id")
        body = section.get("text")
        if isinstance(section_id, str) and isinstance(body, str) and body:
            rows.append((section_id, body))
    return tuple(rows)


def covered() -> tuple[str, ...]:
    """Doc ids in this batch whose extract file is present."""
    directory = _extracted()
    return tuple(doc for doc in _DOCS if (directory / _filename(doc)).is_file())


def children() -> tuple[Node, ...]:
    """Arcs those documents assign. Empty when none of them allocates an arc."""
    directory = _extracted()
    nodes: list[Node] = []
    for doc in covered():
        for section_id, text in _sections(directory / _filename(doc)):
            nodes.extend(parse_assignments(text, f"iso:{doc}§{section_id}"))
    return tuple(nodes)
