"""Arcs under root arc 1. The fixture is an invented table of the same shape, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.arc1 import children

_BODY = """
Primary integer value Resulting integer-valued Unicode label (Non-integer) Unicode label Secondary identifier
8 "8" "Sprocket" sprocket See Z.2
7 "7" "Gasket" gasket (washer) See Z.1
A cited sample flange(4) is not an assigned arc.
EXAMPLE: 9 "9" "Flange" flange
Example: {root(1) gasket(7) cog(3) sprocket(99)}
"""


def _index(directory: Path, body: str | None, section_id: str = "A.4.2") -> Path:
    path = directory / "X.660-2099-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        if body is not None:
            connection.execute(
                "INSERT INTO sections (section_id, body) VALUES (?, ?)",
                (section_id, body),
            )
    return path


def test_assigned_rows_become_children_and_examples_do_not(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _BODY))
    assert [node.oid for node in nodes] == ["1.7", "1.8"]
    assert nodes[0].names == ("gasket", "washer")
    assert nodes[0].unicode_labels == ("7", "Gasket")
    assert nodes[1].names == ("sprocket",)
    assert nodes[0].parent == "1"
    assert nodes[0].cite == "X.660§A.4.2"
    assert all(name not in {"flange", "cog"} for node in nodes for name in node.names)


def test_a_name_and_number_without_the_table_assigns_nothing(tmp_path: Path) -> None:
    body = "EXAMPLE: {gasket(7) sprocket(8)} flange(4)"
    with pytest.raises(LibError, match="no arcs assigned") as caught:
        children(_index(tmp_path, body))
    assert caught.value.hint
    assert caught.value.action


def test_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_missing_clause_names_the_remedy(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="A.4.2") as caught:
        children(_index(tmp_path, None))
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_assigns_four_arcs_under_iso() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children()
    assert [node.oid for node in nodes] == ["1.0", "1.1", "1.2", "1.3"]
    assert [node.names for node in nodes] == [
        ("standard",),
        ("registration-authority",),
        ("member-body",),
        ("identified-organization",),
    ]
