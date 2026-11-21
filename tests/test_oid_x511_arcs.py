"""Operation and module arcs under 2.5. The fixture is invented assignment text."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.x511_arcs import children

_DEEPER = """
sprocket OBJECT IDENTIFIER ::= { joint-iso-itu-t(2) ds(5) module(1) 3 }
gasket OBJECT IDENTIFIER ::= { sprocket 8 }
washer OBJECT IDENTIFIER ::= { joint-iso-itu-t(2) ds(5) 4 }
EXAMPLE: flange OBJECT IDENTIFIER ::= { sprocket 9 }
"""

_SHALLOW = """
sprocket OBJECT IDENTIFIER ::= { joint-iso-itu-t(2) ds(5) 7 }
gasket OBJECT IDENTIFIER ::= { joint-iso-itu-t(2) ds(5) 4 }
EXAMPLE: flange OBJECT IDENTIFIER ::= { joint-iso-itu-t(2) ds(5) module(1) 3 }
"""


def _index(directory: Path, sections: dict[str, str]) -> Path:
    path = directory / "X.511-2099-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            list(sections.items()),
        )
    return path


def test_a_two_level_assignment_whose_parent_is_not_the_root(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"A.1": _DEEPER}))
    assert [(node.oid, node.parent, node.names, node.cite) for node in nodes] == [
        ("2.5.1.3", "2.5.1", ("sprocket",), "X.511§A.1"),
        ("2.5.1.3.8", "2.5.1.3", ("gasket",), "X.511§A.1"),
    ]
    assert all(node.unicode_labels == () for node in nodes)
    assert "2.5.4" not in {node.oid for node in nodes}
    assert all(name != "flange" for node in nodes for name in node.names)


def test_direct_children_of_the_root_yield_an_empty_tuple(tmp_path: Path) -> None:
    assert children(_index(tmp_path, {"A.1": _SHALLOW})) == ()


def test_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.511-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_x511_module_arc() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.511-*.sqlite3"))
    if not indexes:
        pytest.skip("X.511 is not indexed")
    nodes = children()
    assert [(node.oid, node.names, node.parent, node.cite) for node in nodes] == [
        ("2.5.1.2.9", ("DirectoryAbstractService",), "2.5.1.2", "X.511§15.4"),
    ]
    assert nodes[0].unicode_labels == ()
    assert all(node.parent != "2.5" for node in nodes)
