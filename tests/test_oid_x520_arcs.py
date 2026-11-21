"""Attribute arcs under 2.5.4. The fixture is an invented assignment fragment, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.x520_arcs import children

_BODY = """
gasket OBJECT IDENTIFIER ::= {id-at 4}
sprocket OBJECT IDENTIFIER ::= {id-at 4}
sprocket OBJECT IDENTIFIER ::= {id-at 7 1}
-- washer OBJECT IDENTIFIER ::= {id-at 5}
pinion OBJECT IDENTIFIER ::= {id-mr 3}
attributeType OBJECT IDENTIFIER ::= {joint-iso-itu-t(2) ds(5) 4}
EXAMPLE: flange OBJECT IDENTIFIER ::= {id-at 6}
"""


def _index(directory: Path, body: str | None, section_id: str = "Z.4") -> Path:
    path = directory / "X.520-2099-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        if body is not None:
            connection.execute(
                "INSERT INTO sections (section_id, body) VALUES (?, ?)",
                (section_id, body),
            )
    return path


def test_assignments_under_the_attribute_arc(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _BODY))
    assert [(node.oid, node.names, node.parent, node.cite) for node in nodes] == [
        ("2.5.4.4", ("gasket", "sprocket"), "2.5.4", "X.520§Z.4"),
        ("2.5.4.7.1", ("sprocket",), "2.5.4", "X.520§Z.4"),
    ]
    assert all(node.unicode_labels == () for node in nodes)
    assert all(name not in {"washer", "pinion", "flange", "attributeType"} for node in nodes for name in node.names)
    assert "2.5.4" not in {node.oid for node in nodes}


def test_comments_and_examples_assign_nothing(tmp_path: Path) -> None:
    body = "-- gasket OBJECT IDENTIFIER ::= {id-at 4}\nEXAMPLE: sprocket OBJECT IDENTIFIER ::= {id-at 5}\n"
    assert children(_index(tmp_path, body)) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.520-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_attribute_arcs() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.520-*.sqlite3"))
    if not indexes:
        pytest.skip("X.520 is not indexed")
    nodes = children()
    assert any(node.oid.startswith("2.5.") for node in nodes)
    assert all(node.parent == "2.5.4" for node in nodes)
    assert all(node.oid.startswith("2.5.4.") for node in nodes)
    assert all(len(node.oid.split(".")) > 3 for node in nodes)
