"""The direct child of iso whose primary integer is 6.

An assignment is one object-identifier value of exactly that arc: `iso` or `iso(1)`, then primary
integer 6, and nothing further. A longer value names a descendant. Text from an example marker
onward is not an assignment. `children` reads the imported ITU indexes and ISO extracts and returns
the arc when one of them assigns it. Clause text is not stored.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node

_OID = "1.6"
_PARENT = "1"
_NUMBER = "6"
_HYPHEN_BREAK = re.compile(r"-\s+")
_EXAMPLE = re.compile(r"\bexamples?\b", re.IGNORECASE)
_NAME = r"[A-Za-z][A-Za-z0-9-]*"
# The closing brace ends the value. A further component is a descendant, not this arc.
_ASSIGNED = re.compile(
    rf"(?:(?P<left>{_NAME})\s+)?(?:OBJECT\s+IDENTIFIER|ID)\s*::=\s*"
    rf"\{{\s*(?i:iso)(?:\s*\(\s*1\s*\))?\s+"
    rf"(?:(?P<arc>{_NAME})\s*\(\s*{_NUMBER}\s*\)|{_NUMBER})\s*\}}"
)


def parse_assignments(text: str, cite: str) -> tuple[Node, ...]:
    """One node when `text` assigns primary integer 6 directly under iso. Otherwise empty.

    The name in the braces is the arc name. A bare `6` uses the name on the left of `::=`.
    `cite` is stored on the node. The text is not.
    """
    assignment = _EXAMPLE.split(text, maxsplit=1)[0]
    flat = _HYPHEN_BREAK.sub("-", " ".join(assignment.split()))
    match = _ASSIGNED.search(flat)
    if match is None:
        return ()
    name = match.group("arc") or match.group("left")
    if not name:
        return ()
    return (
        Node(
            oid=_OID,
            parent=_PARENT,
            names=(name,),
            unicode_labels=(_NUMBER,),
            cite=cite,
        ),
    )


def _require(path: Path, label: str, action: str) -> None:
    if path.is_dir():
        return
    raise LibError(
        f"{label} not found: {path}",
        "itu_read('X.660§A.4.2')",
        action,
    )


def _from_itu(directory: Path) -> Node | None:
    for path in sorted(directory.glob("*.sqlite3")):
        rec = path.stem.split("-", 1)[0]
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT section_id, body FROM sections ORDER BY ord").fetchall()
        for section_id, body in rows:
            if not isinstance(section_id, str) or not isinstance(body, str) or not body:
                continue
            found = parse_assignments(body, f"{rec}§{section_id}")
            if found:
                return found[0]
    return None


def _iso_cite(path: Path, payload: dict[str, object], section_id: str) -> str:
    doc = payload.get("doc")
    label = doc if isinstance(doc, str) and doc else path.stem
    return f"iso:{label}§{section_id}"


def _from_iso(directory: Path) -> Node | None:
    for path in sorted(directory.glob("*.json")):
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        sections = payload.get("sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_id = section.get("id")
            text = section.get("text")
            if not isinstance(section_id, str) or not isinstance(text, str) or not text:
                continue
            found = parse_assignments(text, _iso_cite(path, payload, section_id))
            if found:
                return found[0]
    return None


def children(itu_index: Path | None = None, iso_extracted: Path | None = None) -> tuple[Node, ...]:
    """Arc 1.6 when an imported ITU or ISO document assigns it. No assignment means an empty tuple.

    `itu_index` defaults to the ITU clause indexes. `iso_extracted` defaults to the ISO extracts.
    A missing directory is an error. An empty result means neither library assigns the arc.
    """
    itu = collection_home("itu") / "index" if itu_index is None else itu_index
    iso = collection_home("iso") / "extracted" if iso_extracted is None else iso_extracted
    _require(itu, "ITU index", "primarysource itu index X.660")
    _require(iso, "ISO extract", "primarysource iso import")
    found = _from_itu(itu) or _from_iso(iso)
    if found is None:
        return ()
    return (found,)
