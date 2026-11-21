"""The `oid-node/1` record: one arc, its names, and the clause that assigns it.

The file is the interchange. A Python, Rust, or JavaScript reader needs only JSON. This module writes it; it
does not fetch a registry and it does not carry the clause text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from primarysource.errors import LibError

FORMAT = "oid-node/1"

# A PDF line break often lands inside an identifier (`joint-iso- ccitt`). Join that before reading names.
_HYPHEN_BREAK = re.compile(r"-\s+")
_ROW = re.compile(
    r'(?P<number>\d+)\s+"(?P<integer_label>[^"]+)"\s+"(?P<unicode>[^"]+)"\s+'
    r"(?P<name>[a-z][a-z0-9-]*)"
    r"(?:\s*\((?P<synonyms>[^)]*)\))?"
)
_NAME = re.compile(r"[a-z][a-z0-9-]*")
_NOT_A_NAME = frozenset({"see", "and"})


@dataclass(frozen=True, slots=True)
class Node:
    """One arc. `oid` is the dotted form (`0`, later `2.1`). `cite` is a primarysource ref, not the clause."""

    oid: str
    names: tuple[str, ...]
    unicode_labels: tuple[str, ...]
    cite: str
    parent: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "oid": self.oid,
            "parent": self.parent,
            "names": list(self.names),
            "unicode_labels": list(self.unicode_labels),
            "cite": self.cite,
        }


def parse_root_table(text: str, cite: str) -> tuple[Node, ...]:
    """The top-arc table: number, two quoted labels, a secondary identifier, and optional synonyms in parentheses.

    `cite` is stored on every node. The clause text is not."""
    flat = _HYPHEN_BREAK.sub("-", " ".join(text.split()))
    nodes: list[Node] = []
    seen: set[str] = set()
    for match in _ROW.finditer(flat):
        oid = match["number"]
        if oid in seen:
            continue
        seen.add(oid)
        names = [match["name"]]
        if match["synonyms"]:
            for name in _NAME.findall(match["synonyms"]):
                if name not in names and name not in _NOT_A_NAME:
                    names.append(name)
        nodes.append(
            Node(
                oid=oid,
                names=tuple(names),
                unicode_labels=(match["integer_label"], match["unicode"]),
                cite=cite,
            )
        )
    if not nodes:
        raise LibError(
            "no root arcs in the clause",
            "the clause should be the top-arc table (number, quoted labels, identifier)",
        )
    return tuple(nodes)


def document(nodes: tuple[Node, ...]) -> str:
    """The interchange file: `oid-node/1` and one object per arc. No footer, so another language can parse it."""
    payload = {"format": FORMAT, "nodes": [node.as_dict() for node in nodes]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
