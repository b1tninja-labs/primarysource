"""Arcs directly under root arc 0. The fixture is an invented table, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.arc0 import children

_TABLE = """
Primary integer value Resulting integer-valued Unicode label (Non-integer) Unicode label
Secondary identifier Authority
4 "4" "Gasket" gasket See Z.1
7 "7" (see Z.2) sprocket- washer See Z.2
8 "8" "Widget" widget See Z.3
10 "10" "Rivet" rivet See Z.4
EXAMPLE: {acme(4) foundry(11) ...} is a company arc inside an example.
{gasket(4) sprocket(7) pinion(3)} is illustrative only.
"""


def _index(directory: Path, body: str, section_id: str = "A.3.2") -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.execute(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            (section_id, body),
        )
    return path


def test_children_read_the_assignment_table_and_skip_examples(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _TABLE))
    assert [node.oid for node in nodes] == ["0.4", "0.7", "0.8", "0.10"]
    assert [node.names for node in nodes] == [("gasket",), ("sprocket-washer",), ("widget",), ("rivet",)]
    assert nodes[0].unicode_labels == ("4", "Gasket")
    assert nodes[1].unicode_labels == ("7",)
    assert nodes[0].parent == "0"
    assert nodes[0].cite == "X.9§A.3.2"
    assert "foundry" not in {name for node in nodes for name in node.names}
    assert "pinion" not in {name for node in nodes for name in node.names}
    assert "acme" not in {name for node in nodes for name in node.names}


def test_a_clause_without_the_table_is_an_error(tmp_path: Path) -> None:
    body = "This clause discusses arcs in general. EXAMPLE: {acme(4) foundry(11)}."
    with pytest.raises(LibError, match="no arcs under 0"):
        children(_index(tmp_path, body))


def test_a_missing_index_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="not found"):
        children(tmp_path / "X.660-2011-07.sqlite3")


def test_a_missing_clause_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no clause"):
        children(_index(tmp_path, _TABLE, section_id="A.9.9"))


def test_imported_x660_children_of_arc_0() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children(indexes[-1])
    assert [node.oid for node in nodes] == ["0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.9"]
    assert [node.names for node in nodes] == [
        ("recommendation",),
        ("question",),
        ("administration",),
        ("network-operator",),
        ("identified-organization",),
        ("r-recommendation",),
        ("data",),
    ]
    assert all(node.parent == "0" for node in nodes)
