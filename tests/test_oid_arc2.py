"""Arcs under root arc 2. The fixture is an invented table of the same shape, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.arc2 import children

_TABLE = """
Primary integer value Resulting integer-valued Unicode label (Non-integer) Unicode label Secondary identifier
8 "8" "Sprocket" sprocket See Z.2
7 "7" "Gasket" gasket (washer) See Z.1
A cited sample flange(4) is not an assigned arc.
EXAMPLE: 9 "9" "Flange" flange
Example: {joint-iso-itu-t(2) widget(3) cog(99)}
"""

_ALLOCATED = """
An arc beneath joint-iso-itu-t has been allocated to the gasket office, with a primary integer
value of 4 and a non-integer Unicode label of "Gasket" and a secondary identifier of gasket
(washer - see Z.1). Arcs beneath this use another table: Primary integer value Resulting
integer-valued Unicode label Secondary identifier 1 "1" tooth
"""

_OID = """
The sprocket workshop has been assigned an arc which produces the value
{joint- iso-itu-t(2) sprocket(8)} and the IRI "/Joint-ISO-ITU-T/Sprocket".
A longer path {joint-iso-itu-t(2) sprocket(8) tooth(1)} is under that arc.
EXAMPLE: {joint-iso-itu-t(2) widget(9)} "/Joint-ISO-ITU-T/Widget"
"""


def _index(directory: Path, sections: dict[str, str] | None) -> Path:
    path = directory / "X.660-2099-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        if sections:
            connection.executemany(
                "INSERT INTO sections (section_id, body) VALUES (?, ?)",
                list(sections.items()),
            )
    return path


def test_assigned_rows_become_children_and_examples_do_not(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"A.5.2": _TABLE}))
    assert [node.oid for node in nodes] == ["2.7", "2.8"]
    assert nodes[0].names == ("gasket", "washer")
    assert nodes[0].unicode_labels == ("7", "Gasket")
    assert nodes[1].names == ("sprocket",)
    assert nodes[0].parent == "2"
    assert nodes[0].cite == "X.660§A.5.2"
    assert all(name not in {"flange", "widget", "cog"} for node in nodes for name in node.names)


def test_prose_assignment_and_direct_oid_skip_deeper_rows(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"A.5.4": _ALLOCATED, "A.5.5": _OID}))
    assert [node.oid for node in nodes] == ["2.4", "2.8"]
    assert nodes[0].names == ("gasket", "washer")
    assert nodes[0].unicode_labels == ("4", "Gasket")
    assert nodes[0].cite == "X.660§A.5.4"
    assert nodes[1].names == ("sprocket",)
    assert nodes[1].unicode_labels == ("8", "Sprocket")
    assert nodes[1].cite == "X.660§A.5.5"
    assert nodes[1].parent == "2"
    assert all(name not in {"tooth", "widget"} for node in nodes for name in node.names)
    assert "2.1" not in {node.oid for node in nodes}


def test_examples_alone_assign_nothing(tmp_path: Path) -> None:
    body = 'EXAMPLE: {joint-iso-itu-t(2) gasket(7)} and 8 "8" "Sprocket" sprocket'
    with pytest.raises(LibError, match="no arcs under 2") as caught:
        children(_index(tmp_path, {"A.5.4": body}))
    assert caught.value.hint
    assert caught.value.action


def test_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_missing_clause_names_the_remedy(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="A.5") as caught:
        children(_index(tmp_path, None))
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_children_of_arc_2() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children()
    assert [node.oid for node in nodes] == ["2.16", "2.17"]
    assert [node.names for node in nodes] == [("country",), ("registration-procedures",)]
