"""Arcs under joint-iso-itu-t from 40 upward. The fixture is invented text, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.j_late import children

_BODY = """
{joint-iso-itu-t(2) washer(4)}
{joint-iso-itu-t(2) gasket(40)}
primary integer value of 51 and a non-integer Unicode label of "Sprocket" and a secondary identifier of sprocket
{joint-iso-itu-t(2) example(999)}
{joint-iso-itu-t example(999) gasket(40) sprocket(8)}
EXAMPLE: {joint-iso-itu-t(2) flange(42)}
Example: {2 41}
"""


def _index(directory: Path, body: str | None, section_id: str = "A.5.2") -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        if body is not None:
            connection.execute(
                "INSERT INTO sections (section_id, body) VALUES (?, ?)",
                (section_id, body),
            )
    return path


def test_late_assignments_are_kept_and_lower_numbers_are_not(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _BODY))
    assert [node.oid for node in nodes] == ["2.40", "2.51", "2.999"]
    assert [node.names for node in nodes] == [("gasket",), ("sprocket",), ("example",)]
    assert nodes[0].unicode_labels == ("40",)
    assert nodes[1].unicode_labels == ("51", "Sprocket")
    assert nodes[0].parent == "2"
    assert nodes[0].cite == "X.9§A.5.2"
    assert all(node.parent == "2" for node in nodes)
    dropped = {"washer", "flange", "sprocket-8"}
    assert dropped.isdisjoint({name for node in nodes for name in node.names})


def test_a_longer_value_does_not_assign_the_second_arc(tmp_path: Path) -> None:
    body = "{joint-iso-itu-t example(999) gasket(40) sprocket(8)}"
    assert children(_index(tmp_path, body)) == ()


def test_an_example_marker_assigns_nothing(tmp_path: Path) -> None:
    body = "Example: {joint-iso-itu-t(2) gasket(40)} {2 41}"
    assert children(_index(tmp_path, body)) == ()


def test_no_late_assignment_is_empty(tmp_path: Path) -> None:
    body = "{joint-iso-itu-t(2) washer(4)} primary integer value of 17 and a secondary identifier of sprocket"
    assert children(_index(tmp_path, body)) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_assigns_no_late_joint_arcs() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    assert children(indexes[-1]) == ()
