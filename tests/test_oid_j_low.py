"""Arcs 2.0 through 2.9. The fixture is invented assignment text, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.j_low import children

_BODY = """
sprocket OBJECT IDENTIFIER ::= {joint- iso-itu-t(2) sprocket(7)}
gasket ID ::= {joint-iso-itu-t gasket(4)}
washer ID ::= {joint-iso-itu-t washer(4)}
rivet ID ::= {joint-iso-itu-t rivet(16)}
pinion ID ::= {joint-iso-itu-t gasket(4) pinion(3)}
EXAMPLE: flange ID ::= {joint-iso-itu-t flange(3)}
{gasket(4) sprocket(7)} is not an assignment.
"""


def _index(directory: Path, body: str | None, section_id: str = "Z.4") -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        if body is not None:
            connection.execute(
                "INSERT INTO sections (section_id, body) VALUES (?, ?)",
                (section_id, body),
            )
    return path


def test_one_arc_assignments_in_range_become_children(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _BODY))
    assert [node.oid for node in nodes] == ["2.4", "2.7"]
    assert [node.names for node in nodes] == [("gasket",), ("sprocket",)]
    assert nodes[0].unicode_labels == ("4",)
    assert nodes[1].unicode_labels == ("7",)
    assert nodes[0].parent == "2"
    assert nodes[0].cite == "X.9§Z.4"
    assert all(name not in {"washer", "rivet", "pinion", "flange"} for node in nodes for name in node.names)


def test_nothing_in_range_is_empty(tmp_path: Path) -> None:
    body = "rivet ID ::= {joint-iso-itu-t rivet(16)}\nEXAMPLE: flange ID ::= {joint-iso-itu-t flange(1)}"
    assert children(_index(tmp_path, body)) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_joint_arcs_through_nine() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children()
    assert [node.oid for node in nodes] == ["2.5"]
    assert [node.names for node in nodes] == [("ds",)]
    assert nodes[0].parent == "2"
    assert nodes[0].cite == "X.501§31.1.9"
    assert nodes[0].unicode_labels == ("5",)
