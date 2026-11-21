"""Arcs an RFC registers under 0, 1, or 2.

`children` holds the identifiers and numbers from those registrations. `parse_assignments` reads an
invented fragment of the same shape. Neither one stores section text.
"""

from __future__ import annotations

import re

from primarysource.errors import LibError
from primarysource.oid.tree import Node

_ASSIGNMENT = re.compile(r"(?<![A-Za-z0-9-])([A-Za-z][A-Za-z0-9-]*)\s+OBJECT\s+IDENTIFIER\s*::=\s*\{([^{}]*)\}")
_COMPONENT = re.compile(r"([A-Za-z][A-Za-z0-9-]*)\s*\(\s*(\d+)\s*\)|([A-Za-z][A-Za-z0-9-]*)|(\d+)")

# identifier, number, parent number path, cite. Parents already registered elsewhere stay as the parent OID.
_REGISTRATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("zeroDotZero", "0.0", "0", "RFC2578§2"),
    ("internet", "1.3.6.1", "1.3.6", "RFC1155§3.1"),
    ("directory", "1.3.6.1.1", "1.3.6.1", "RFC1155§3.1"),
    ("mgmt", "1.3.6.1.2", "1.3.6.1", "RFC1155§3.1"),
    ("experimental", "1.3.6.1.3", "1.3.6.1", "RFC1155§3.1"),
    ("private", "1.3.6.1.4", "1.3.6.1", "RFC1155§3.1"),
    ("enterprises", "1.3.6.1.4.1", "1.3.6.1.4", "RFC1155§3.1.4"),
    ("security", "1.3.6.1.5", "1.3.6.1", "RFC2578§2"),
    ("snmpV2", "1.3.6.1.6", "1.3.6.1", "RFC2578§2"),
    ("snmpDomains", "1.3.6.1.6.1", "1.3.6.1.6", "RFC2578§2"),
    ("snmpProxys", "1.3.6.1.6.2", "1.3.6.1.6", "RFC2578§2"),
    ("snmpModules", "1.3.6.1.6.3", "1.3.6.1.6", "RFC2578§2"),
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
            raise LibError(
                "a component is not a name, a name(number), or a number",
                "an assignment has the form name OBJECT IDENTIFIER ::= { parent name(number) }",
            )
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
            raise LibError(
                "a component is not a name, a name(number), or a number",
                "an assignment has the form name OBJECT IDENTIFIER ::= { parent name(number) }",
            )
        pos = _skip(body, match.end())
    return parts


def parse_assignments(text: str, cite: str) -> tuple[Node, ...]:
    """Nodes for each `name OBJECT IDENTIFIER ::= { parent name(number) }` in an invented fragment.

    A `name(number)` in the braces is one step of the path. The name on the left is the arc being
    assigned. `cite` is stored on every node.
    """
    known: dict[str, str] = {}
    nodes: list[Node] = []
    for match in _ASSIGNMENT.finditer(text):
        name, body = match.group(1), match.group(2)
        parts = _components(body, known)
        if not parts:
            continue
        oid = ".".join(parts)
        parent = ".".join(parts[:-1]) if len(parts) > 1 else None
        known[name] = oid
        nodes.append(Node(oid=oid, names=(name,), unicode_labels=(), cite=cite, parent=parent))
    if not nodes:
        raise LibError(
            "the fragment assigns nothing",
            "an assignment has the form name OBJECT IDENTIFIER ::= { parent name(number) }",
        )
    return tuple(nodes)


def children() -> tuple[Node, ...]:
    """The arcs registered by RFC1155 and RFC2578 under 0 and 1. No enterprise number and no mib-2 arc."""
    return tuple(
        Node(oid=oid, parent=parent, names=(name,), unicode_labels=(), cite=cite)
        for name, oid, parent, cite in _REGISTRATIONS
    )
