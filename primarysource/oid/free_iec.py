"""Arcs assigned by the free IEC publications that are not joint ISO/IEC editions.

An assignment is an OBJECT IDENTIFIER value, or a name(number) the clause allocates. A mention of
ISO or ITU-T is not an assignment. Clause text is not stored.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

# A PDF line break often lands inside an identifier. Join that, and leave a comment marker alone.
_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-z0-9])-\s+(?=[A-Za-z0-9])")
_EXAMPLE = re.compile(r"\b(?:EXAMPLE|Example)\b")
_ASSIGNMENT = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*\{(?P<body>[^{}]*)\}")
_COMPONENT = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\s*\(\s*(?P<number>\d+)\s*\)|(?P<digits>\d+)")
_ALLOCATION = re.compile(r"\b(?:allocat\w*|assign\w*)\b", re.IGNORECASE)
_NAME_NUMBER = re.compile(r"(?P<name>[A-Za-z][A-Za-z0-9-]*)\(\s*(?P<number>\d+)\s*\)")
_SENTENCE = re.compile(r"[.!?]")
# These name an ISO or ITU-T arc. Naming one is a mention, not an assignment by the publication.
_MENTION = frozenset({"iso", "itu", "itu-t", "ccitt", "joint-iso-itu-t", "joint-iso-ccitt"})


def _flatten(text: str) -> str:
    head = _EXAMPLE.split(text, maxsplit=1)[0]
    return _HYPHEN_BREAK.sub("-", " ".join(head.split()))


def _commented(text: str, start: int) -> bool:
    """True when `--` introduces this identifier, which marks an arc the clause does not assign."""
    index = start
    while index > 0 and text[index - 1].isspace():
        index -= 1
    return index >= 2 and text[index - 2 : index] == "--"


def _mention(name: str) -> bool:
    return name.lower() in _MENTION


def _oid_key(node: Node) -> tuple[int, ...]:
    return tuple(int(part) for part in node.oid.split("."))


def _remember(found: dict[str, Node], oid: str, parent: str | None, name: str, number: str, cite: str) -> None:
    current = found.get(oid)
    if current is None:
        found[oid] = Node(oid=oid, parent=parent, names=(name,), unicode_labels=(number,), cite=cite)
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


def _numbers(body: str) -> tuple[str, ...]:
    numbers: list[str] = []
    for match in _COMPONENT.finditer(body):
        number = match.group("number")
        digits = match.group("digits")
        if number is not None:
            numbers.append(str(int(number)))
        elif digits is not None:
            numbers.append(str(int(digits)))
    return tuple(numbers)


def _from_values(text: str, cite: str, found: dict[str, Node]) -> None:
    for match in _ASSIGNMENT.finditer(text):
        name = match.group("name")
        if name is None or _mention(name) or _commented(text, match.start()):
            continue
        numbers = _numbers(match.group("body") or "")
        if not numbers:
            continue
        parent = ".".join(numbers[:-1]) if len(numbers) > 1 else None
        _remember(found, ".".join(numbers), parent, name, numbers[-1], cite)


def _runs(text: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    runs: list[tuple[tuple[str, str], ...]] = []
    current: list[tuple[str, str]] = []
    pos = 0
    for match in _NAME_NUMBER.finditer(text):
        name = match.group("name")
        number = match.group("number")
        if name is None or number is None:
            continue
        if current and text[pos : match.start()].strip():
            runs.append(tuple(current))
            current = []
        current.append((name, str(int(number))))
        pos = match.end()
    if current:
        runs.append(tuple(current))
    return tuple(runs)


def _from_allocations(text: str, cite: str, found: dict[str, Node]) -> None:
    for match in _ALLOCATION.finditer(text):
        tail = text[match.end() :]
        end = _SENTENCE.search(tail)
        clause = tail[: end.start()] if end is not None else tail
        for run in _runs(clause):
            if not run or all(_mention(name) for name, _number in run):
                continue
            name, number = run[-1]
            if _mention(name):
                continue
            numbers = tuple(item[1] for item in run)
            parent = ".".join(numbers[:-1]) if len(numbers) > 1 else None
            _remember(found, ".".join(numbers), parent, name, number, cite)


def _take(text: str, cite: str, found: dict[str, Node]) -> None:
    flat = _flatten(text)
    _from_values(flat, cite, found)
    _from_allocations(_ASSIGNMENT.sub(" ", flat), cite, found)


def _directory(extracted: Path | None) -> Path:
    path = collection_home("iec") / "extracted" if extracted is None else extracted
    if path.is_dir():
        return path
    raise LibError(
        f"IEC extract not found: {path}",
        "iec_docs lists what is imported",
        "primarysource iec import",
    )


def _load(path: Path) -> dict[str, object]:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LibError(
            f"IEC extract is not readable: {path.name}",
            "iec_docs lists what is imported",
            "primarysource iec import",
        ) from exc
    if not isinstance(loaded, dict):
        raise LibError(
            f"IEC extract is not a document: {path.name}",
            "iec_docs lists what is imported",
            "primarysource iec import",
        )
    return {key: value for key, value in loaded.items() if isinstance(key, str)}


def _doc_id(path: Path, payload: dict[str, object]) -> str:
    doc = payload.get("doc")
    if isinstance(doc, str) and doc:
        return doc
    return path.stem


def _sections(payload: dict[str, object]) -> tuple[tuple[str, str], ...]:
    raw = payload.get("sections")
    if not isinstance(raw, list):
        return ()
    sections: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        section_id = item.get("id")
        text = item.get("text")
        if isinstance(section_id, str) and isinstance(text, str) and text.strip():
            sections.append((section_id, text))
    return tuple(sections)


def _documents(directory: Path) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    documents: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for path in sorted(directory.glob("*.json")):
        payload = _load(path)
        documents.append((_doc_id(path, payload), _sections(payload)))
    return tuple(documents)


def covered(extracted: Path | None = None) -> tuple[str, ...]:
    """Doc ids of every IEC extract opened, in file-name order.

    `extracted` defaults to the IEC extract directory. A missing directory is an error.
    An empty directory is an empty tuple.
    """
    return tuple(doc for doc, _sections in _documents(_directory(extracted)))


def children(extracted: Path | None = None) -> tuple[Node, ...]:
    """Arcs those publications assign.

    `extracted` defaults to the IEC extract directory. No assignment is an empty tuple.
    A missing directory is an error.
    """
    found: dict[str, Node] = {}
    for doc, sections in _documents(_directory(extracted)):
        for section_id, text in sections:
            _take(text, f"iec:{doc}§{section_id}", found)
    return tuple(sorted(found.values(), key=_oid_key))
