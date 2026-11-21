"""Arcs under root arc 0 from clauses after the main table. The fixture is an invented table."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.arc0_more import children

_TABLE = """
Primary integer value Resulting integer-valued Unicode label (Non-integer) Unicode label
Secondary identifier
{acme(4) foundry(11)} is a company arc.
4 "4" "Gasket" gasket See Z.1
7 "7" (see Z.2) sprocket- washer See Z.2
EXAMPLE: 9 "9" "Pinion" pinion
{gasket(4) sprocket(7) pinion(3)} is illustrative only.
"""


def _index(directory: Path, sections: dict[str, str]) -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            list(sections.items()),
        )
    return path


def test_assigned_rows_become_children_and_samples_do_not(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"A.3.5": _TABLE}))
    assert [node.oid for node in nodes] == ["0.4", "0.7"]
    assert [node.names for node in nodes] == [("gasket",), ("sprocket-washer",)]
    assert nodes[0].unicode_labels == ("4", "Gasket")
    assert nodes[1].unicode_labels == ("7",)
    assert nodes[0].parent == "0"
    assert nodes[0].cite == "X.9§A.3.5"
    assert "pinion" not in {name for node in nodes for name in node.names}
    assert "acme" not in {name for node in nodes for name in node.names}
    assert "foundry" not in {name for node in nodes for name in node.names}


def test_each_row_keeps_the_clause_that_assigned_it(tmp_path: Path) -> None:
    nodes = children(
        _index(
            tmp_path,
            {
                "A.3.2": '1 "1" "Question" question\n',
                "A.3.8": '7 "7" "Sprocket" sprocket\n',
                "A.3.4": '4 "4" "Gasket" gasket\n',
            },
        )
    )
    assert [node.oid for node in nodes] == ["0.4", "0.7"]
    assert nodes[0].names == ("gasket",)
    assert nodes[1].names == ("sprocket",)
    assert nodes[0].cite == "X.9§A.3.4"
    assert nodes[1].cite == "X.9§A.3.8"
    assert nodes[0].parent == "0"
    assert "question" not in {name for node in nodes for name in node.names}


def test_prose_without_a_table_assigns_nothing(tmp_path: Path) -> None:
    body = "Lower arcs are discussed here. {acme(4) foundry(11)} is a company arc."
    assert children(_index(tmp_path, {"A.3.7": body, "A.6": ""})) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2011-07.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_clauses_outside_the_range_are_not_a_substitute(tmp_path: Path) -> None:
    body = '4 "4" "Gasket" gasket\n'
    with pytest.raises(LibError, match="no clauses") as caught:
        children(_index(tmp_path, {"A.3.2": body}))
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_direct_children_outside_the_main_table() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children(indexes[-1])
    assert [node.oid for node in nodes] == []
