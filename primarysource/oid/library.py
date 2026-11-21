"""Root arcs 0, 1 and 2, plus the child arcs already parsed by the oid modules.

The numbers and names come from the annex table in the owner's ITU library and from those modules. This
module stores neither the clause nor a copy of the arcs.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.tree import Node, document, parse_root_table
from primarysource.refs import Ref
from primarysource.render import render

_CLAUSE = "A.2.2"
_ROOTS = frozenset({"0", "1", "2"})
_OID = re.compile(r"\d+(?:\.\d+)*")


def itu_home(home: Path | None = None) -> Path:
    return collection_home("itu") if home is None else home


def x660_index(home: Path | None = None) -> Path:
    """The newest imported X.660 clause index, by the date in the file name."""
    found = sorted((itu_home(home) / "index").glob("X.660-*.sqlite3"))
    if not found:
        raise LibError(
            "X.660 is not indexed",
            "itu_read('X.660§A.2.2')",
            "primarysource itu fetch X.660 && primarysource itu index X.660",
        )
    return found[-1]


def root_nodes(index: Path | None = None) -> tuple[Node, ...]:
    """Arcs 0, 1 and 2 from X.660 §A.2.2. Anything else in that table is an error, not a quiet extra root."""
    path = x660_index() if index is None else index
    if not path.is_file():
        raise LibError(
            f"X.660 index not found: {path}",
            "itu_read('X.660§A.2.2')",
            "primarysource itu index X.660",
        )
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        row = connection.execute("SELECT body FROM sections WHERE section_id = ?", (_CLAUSE,)).fetchone()
    if row is None or not row[0]:
        raise LibError(
            f"X.660 has no clause {_CLAUSE}",
            "the annex table may have been stored under another clause id",
            "primarysource itu index X.660",
        )
    rec = path.stem.split("-", 1)[0]
    cite = f"{rec}§{_CLAUSE}"
    nodes = parse_root_table(str(row[0]), cite)
    got = {node.oid for node in nodes}
    if got != _ROOTS:
        raise LibError(
            f"X.660 §{_CLAUSE} yielded arcs {', '.join(sorted(got))}, not 0, 1 and 2",
            f"itu_read('{cite}')",
            "primarysource itu index X.660",
        )
    return tuple(sorted(nodes, key=lambda node: int(node.oid)))


def _oid_key(oid: str) -> tuple[int, ...]:
    """Numeric order: ``2.5`` before ``2.16``, and ``1.3`` before ``1.3.6.1``."""
    return tuple(int(part) for part in oid.split("."))


def merge_nodes(nodes: Iterable[Node]) -> tuple[Node, ...]:
    """One node per oid, sorted by `_oid_key`.

    Names union in first-seen order. The cite stays the first node's. The parent stays the first one that
    is set. Unicode labels stay with the first node.
    """
    merged: dict[str, Node] = {}
    for node in nodes:
        current = merged.get(node.oid)
        if current is None:
            merged[node.oid] = node
            continue
        parent = current.parent if current.parent is not None else node.parent
        merged[node.oid] = Node(
            oid=current.oid,
            names=tuple(dict.fromkeys((*current.names, *node.names))),
            unicode_labels=current.unicode_labels,
            cite=current.cite,
            parent=parent,
        )
    return tuple(sorted(merged.values(), key=lambda node: _oid_key(node.oid)))


def _child_nodes() -> tuple[Node, ...]:
    """Arcs from the child modules, in module order. Each module finds its own index.

    ``rfc_arcs.children`` takes no index. The others do, and calling them with none is how they locate it.
    """
    from primarysource.oid import (
        arc0,
        arc0_more,
        arc1,
        arc1_more,
        arc2,
        j_high,
        j_late,
        j_low,
        j_mid,
        rfc_arcs,
    )

    return (
        *arc0.children(),
        *arc0_more.children(),
        *arc1.children(),
        *arc1_more.children(),
        *arc2.children(),
        *j_low.children(),
        *j_mid.children(),
        *j_high.children(),
        *j_late.children(),
        *rfc_arcs.children(),
    )


def _merged_nodes(index: Path | None = None) -> tuple[Node, ...]:
    """The three roots, then every child module, collapsed to one node per oid."""
    return merge_nodes((*root_nodes(index), *_child_nodes()))


def parse_ref(text: str) -> Ref:
    """`0`, `oid:1`, or `oid:2`. A longer OID is not a root arc."""
    body = text.strip()
    if body.startswith("oid:"):
        body = body[4:]
    if body not in _ROOTS:
        raise LibError(
            f"not a root arc: {text!r}",
            "oid_read('0'), oid_read('1'), or oid_read('2')",
        )
    return Ref(doc=body)


def _parse_oid(text: str) -> str:
    body = text.strip()
    if body.startswith("oid:"):
        body = body[4:]
    if _OID.fullmatch(body) is None:
        raise LibError(f"not an oid: {text!r}", "oid_roots()")
    return body


def read(ref: str, index: Path | None = None) -> str:
    """One arc in the merged tree. A unicode line is present when the node has labels."""
    oid = _parse_oid(ref)
    node = {item.oid: item for item in _merged_nodes(index)}.get(oid)
    if node is None:
        raise LibError(f"unknown oid: {oid}", "oid_roots()")
    lines = [f"{node.oid} {' '.join(node.names)}"]
    if node.unicode_labels:
        lines.append(f"unicode: {' '.join(node.unicode_labels)}")
    return render("\n".join(lines), {"cite": node.cite})


def roots(index: Path | None = None) -> str:
    """The three root arcs, one per line, with the clause they come from."""
    nodes = root_nodes(index)
    lines = [f"{node.oid} {' '.join(node.names)}" for node in nodes]
    return render("\n".join(lines), {"cite": nodes[0].cite})


def export(index: Path | None = None) -> str:
    """The `oid-node/1` document for the merged arcs. No footer."""
    return document(_merged_nodes(index))
