"""OID arcs assigned by the low-numbered free ISO and joint ISO/IEC extracts.

An assignment is an ``OBJECT IDENTIFIER`` value, or a ``name(number)`` the clause allocates
under a dotted parent. A bibliographic mention of ITU-T is not an assignment, and neither is
a dotted number used as an example. Text from an example marker onward is ignored. Clause
text is not stored.

``covered`` reports which of these documents opened. ``children`` returns the arcs they
assign. No assignment is an empty tuple.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_DOCS: tuple[str, ...] = (
    "75@2006",
    "79@2026",
    "2382-4@1999",
    "2382-7@2000",
    "2382-15@1999",
    "2382-16@1996",
    "2382-19@1989",
    "2382-36@2019",
    "2382-37@2022",
    "2382@2015",
    "5055@2021",
    "5140@2024",
    "5218@2022",
    "5230@2020",
    "5394@2024",
    "5962@2021",
)

# Bare roots name a parent path. They are not arcs this clause allocates.
_ROOTS: dict[str, str] = {
    "iso": "1",
    "itu-t": "0",
    "itu-r": "0",
    "ccitt": "0",
    "joint-iso-itu-t": "2",
    "joint-iso-ccitt": "2",
}

_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_VALUE = re.compile(
    r"(?<![A-Za-z0-9-])"
    r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*"
    r"\{(?P<body>[^{}]*)\}"
)
_COMPONENT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*\(\s*(\d+)\s*\)|([A-Za-z][A-Za-z0-9-]*)|(\d+)")
_ALLOCATED = re.compile(
    r"\b(?:allocat\w*|assign\w*)\s+(?:the\s+arc\s+|arc\s+)?"
    r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)"
)
_PARENT = re.compile(
    r"\b(?:under|beneath)\s+"
    r"(?:"
    r"(?P<root>iso|itu-t|itu-r|ccitt|joint-iso-itu-t|joint-iso-ccitt)\s*"
    r"(?:\(\s*(?P<root_number>\d+)\s*\))?"
    r"|(?P<dotted>\d+(?:\.\d+)*)"
    r")",
    re.IGNORECASE,
)


def _filename(doc: str) -> str:
    return doc.replace("@", "_") + ".json"


def _directory(extracted: Path | None) -> Path:
    directory = collection_home("iso") / "extracted" if extracted is None else extracted
    if directory.is_dir():
        return directory
    raise LibError(
        f"ISO extract directory not found: {directory}",
        "iso_docs lists what is imported",
        "primarysource iso import",
    )


def _opened(directory: Path) -> tuple[tuple[str, str], ...]:
    opened: list[tuple[str, str]] = []
    for doc in _DOCS:
        path = directory / _filename(doc)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        opened.append((doc, text))
    return tuple(opened)


def _load(text: str) -> dict[str, object] | None:
    try:
        payload: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    loaded: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(key, str):
            loaded[key] = value
    return loaded


def _sections(payload: dict[str, object]) -> list[tuple[str, str]]:
    raw = payload.get("sections")
    if not isinstance(raw, list):
        return []
    sections: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        section_id = item.get("id")
        body = item.get("text")
        if isinstance(section_id, str) and isinstance(body, str) and body.strip():
            sections.append((section_id, body))
    return sections


def _head(text: str) -> str:
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    return _EXAMPLE.split(flat, maxsplit=1)[0]


def _remember(
    found: dict[str, Node],
    known: dict[str, str],
    oid: str,
    parent: str | None,
    names: tuple[str, ...],
    number: str,
    cite: str,
) -> None:
    current = found.get(oid)
    if current is None:
        found[oid] = Node(oid=oid, parent=parent, names=names, unicode_labels=(number,), cite=cite)
    else:
        merged = current.names
        for name in names:
            if name not in merged:
                merged += (name,)
        if merged != current.names:
            found[oid] = Node(
                oid=current.oid,
                parent=current.parent,
                names=merged,
                unicode_labels=current.unicode_labels,
                cite=current.cite,
            )
    for name in names:
        known[name] = oid


def _path(body: str, known: dict[str, str]) -> tuple[list[str], str] | None:
    """Number steps of one value, and the name of its final ``name(number)`` when it has one."""
    numbers: list[str] = []
    final_name = ""
    pos = 0
    length = len(body)
    while pos < length:
        while pos < length and body[pos] in " \t,":
            pos += 1
        if pos >= length:
            break
        match = _COMPONENT.match(body, pos)
        if match is None:
            return None
        named, number, bare, digits = match.group(1), match.group(2), match.group(3), match.group(4)
        final_name = ""
        if named is not None and number is not None:
            numbers.append(str(int(number)))
            final_name = named
        elif digits is not None:
            numbers.append(str(int(digits)))
        elif bare is not None:
            root = _ROOTS.get(bare.lower())
            if root is not None:
                numbers.append(root)
            else:
                prior = known.get(bare)
                if prior is None:
                    return None
                numbers.extend(prior.split("."))
        else:
            return None
        pos = match.end()
    if not numbers:
        return None
    if final_name.lower() in _ROOTS:
        final_name = ""
    return numbers, final_name


def _from_values(head: str, cite: str, found: dict[str, Node], known: dict[str, str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in _VALUE.finditer(head):
        spans.append((match.start(), match.end()))
        name = match.group("name")
        body = match.group("body")
        if name is None or body is None:
            continue
        parsed = _path(body, known)
        if parsed is None:
            continue
        numbers, final_name = parsed
        names = (name,) if not final_name or final_name == name else (name, final_name)
        oid = ".".join(numbers)
        parent = ".".join(numbers[:-1]) if len(numbers) > 1 else None
        _remember(found, known, oid, parent, names, numbers[-1], cite)
    return spans


def _parent_oid(text: str, start: int, end: int) -> str | None:
    before = text[max(0, start - 80) : start]
    after = text[end : end + 80]
    found = list(_PARENT.finditer(before))
    match = found[-1] if found else _PARENT.search(after)
    if match is None:
        return None
    dotted = match.group("dotted")
    if dotted is not None:
        return ".".join(str(int(part)) for part in dotted.split("."))
    root = match.group("root")
    if root is None:
        return None
    number = match.group("root_number")
    if number is not None:
        return str(int(number))
    return _ROOTS.get(root.lower())


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < stop and end > begin for begin, stop in spans)


def _from_allocated(
    head: str,
    cite: str,
    found: dict[str, Node],
    known: dict[str, str],
    spans: list[tuple[int, int]],
) -> None:
    for match in _ALLOCATED.finditer(head):
        if _overlaps(spans, match.start(), match.end()):
            continue
        name = match.group("name")
        number = match.group("number")
        if name is None or number is None or name.lower() in _ROOTS:
            continue
        parent = _parent_oid(head, match.start(), match.end())
        if parent is None:
            continue
        arc = str(int(number))
        _remember(found, known, f"{parent}.{arc}", parent, (name,), arc, cite)


def _from_section(text: str, cite: str, found: dict[str, Node], known: dict[str, str]) -> None:
    head = _head(text)
    spans = _from_values(head, cite, found, known)
    _from_allocated(head, cite, found, known, spans)


def _oid_key(node: Node) -> tuple[int, ...]:
    return tuple(int(part) for part in node.oid.split("."))


def covered(extracted: Path | None = None) -> tuple[str, ...]:
    """Document ids from this set whose extract file opened.

    ``extracted`` defaults to the ISO extracts. A missing directory is an error. A missing
    file is omitted, not an error.
    """
    directory = _directory(extracted)
    return tuple(doc for doc, _text in _opened(directory))


def children(extracted: Path | None = None) -> tuple[Node, ...]:
    """Arcs assigned by those documents.

    ``extracted`` defaults to the ISO extracts. A missing directory is an error. No
    assignment is an empty tuple.
    """
    directory = _directory(extracted)
    found: dict[str, Node] = {}
    for doc, text in _opened(directory):
        payload = _load(text)
        if payload is None:
            continue
        known: dict[str, str] = {}
        for section_id, body in _sections(payload):
            _from_section(body, f"iso:{doc}§{section_id}", found, known)
    return tuple(sorted(found.values(), key=_oid_key))
