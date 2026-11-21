"""The dod arc assigned under org.

`children` returns that arc. `parse_assignments` reads an invented fragment of the same shape.
Section text is not stored. The internet arc under dod is registered elsewhere.
"""

from __future__ import annotations

from primarysource.oid.rfc_arcs import parse_assignments as _parse_assignments
from primarysource.oid.tree import Node


def parse_assignments(text: str, cite: str) -> tuple[Node, ...]:
    """Nodes for each `name OBJECT IDENTIFIER ::= { ... }` in an invented fragment.

    The name on the left is the arc being assigned. A name in the braces is a step of the path.
    `cite` is stored on every node. A fragment that assigns nothing raises `LibError`.
    """
    return _parse_assignments(text, cite)


def children() -> tuple[Node, ...]:
    """The dod arc. internet and every arc under it are registered elsewhere."""
    return (
        Node(
            oid="1.3.6",
            parent="1.3",
            names=("dod",),
            unicode_labels=(),
            cite="RFC2578§2",
        ),
    )
