"""Arcs under root arc 1 outside the A.4.2 table. The fixture is an invented table, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.arc1_more import children

_TABLE = """
Primary integer value Resulting integer-valued Unicode label (Non-integer) Unicode label Secondary identifier
7 "7" "Gasket" gasket See Z.1
8 "8" "Sprocket" sprocket See Z.2
A cited sample pinion(4) is not an assigned arc.
EXAMPLE: 9 "9" "Flange" flange
Example: {root(1) gasket(7) cog(3) sprocket(99)}
"""

_NO_ROWS = """
Arcs below a parent are described here, with no assignment row.
EXAMPLE: {gasket(7) sprocket(8) pinion(3)}
Example: 9 "9" "Flange" flange
"""


def _index(directory: Path, sections: dict[str, str]) -> Path:
    path = directory / "X.660-2099-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            list(sections.items()),
        )
    return path


def test_assigned_rows_become_children_and_examples_do_not(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"A.4.3": _TABLE, "A.6.1": _TABLE}))
    assert [node.oid for node in nodes] == ["1.7", "1.8"]
    assert [node.names for node in nodes] == [("gasket",), ("sprocket",)]
    assert nodes[0].unicode_labels == ("7", "Gasket")
    assert nodes[1].unicode_labels == ("8", "Sprocket")
    assert nodes[0].parent == "1"
    assert nodes[0].cite == "X.660§A.4.3"
    assert nodes[1].cite == "X.660§A.4.3"
    assert all(name not in {"flange", "cog", "pinion"} for node in nodes for name in node.names)


def test_a_later_clause_keeps_its_own_cite(tmp_path: Path) -> None:
    nodes = children(
        _index(
            tmp_path,
            {
                "A.4.4": '2 "2" "Gasket" gasket',
                "A.6.3": '5 "5" "Sprocket" sprocket',
            },
        )
    )
    assert [(node.oid, node.names, node.cite) for node in nodes] == [
        ("1.2", ("gasket",), "X.660§A.4.4"),
        ("1.5", ("sprocket",), "X.660§A.6.3"),
    ]


def test_text_with_no_assignment_row_is_empty(tmp_path: Path) -> None:
    sections = {
        clause: _NO_ROWS
        for clause in ("A.4.3", "A.4.4", "A.4.5", "A.4.6", "A.4.7", "A.6", "A.6.1", "A.6.2", "A.6.3", "A.6.4")
    }
    assert children(_index(tmp_path, sections)) == ()


def test_an_a42_table_is_not_read(tmp_path: Path) -> None:
    assert children(_index(tmp_path, {"A.4.2": _TABLE})) == ()


def test_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_assigns_no_further_arcs_under_1() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children()
    assert [node.oid for node in nodes] == []
