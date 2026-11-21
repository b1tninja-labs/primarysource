"""Arcs 2.20 through 2.28. The fixture is invented text, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.j_high import children

_BODY = """
Under joint-iso-itu-t a bench arc carries a primary integer value of 17
and a secondary identifier of cog.
{joint-iso-itu-t(2) gasket(20)} is recorded.
Under joint-iso-itu-t another bench arc carries a primary integer value of 25
and a non-integer Unicode label of "Sprocket" and a secondary identifier of sprocket.
{joint-iso-itu-t(2) washer(29)} is outside the high range.
EXAMPLE: {joint-iso-itu-t(2) flange(22)} is a sketch on the whiteboard.
"""


def _index(directory: Path, body: str | None, section_id: str = "J.1") -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        if body is not None:
            connection.execute(
                "INSERT INTO sections (section_id, body) VALUES (?, ?)",
                (section_id, body),
            )
    return path


def test_assigned_high_arcs_are_kept_and_examples_are_not(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _BODY))
    assert [node.oid for node in nodes] == ["2.20", "2.25"]
    assert [node.names for node in nodes] == [("gasket",), ("sprocket",)]
    assert nodes[0].unicode_labels == ("20",)
    assert nodes[1].unicode_labels == ("25", "Sprocket")
    assert nodes[0].parent == "2"
    assert nodes[1].parent == "2"
    assert nodes[0].cite == "X.9§J.1"
    assert all(name not in {"cog", "washer", "flange"} for node in nodes for name in node.names)


def test_nothing_in_range_is_an_empty_result(tmp_path: Path) -> None:
    body = (
        "Under joint-iso-itu-t a bench arc carries a primary integer value of 16 and a secondary identifier of cog."
    )
    assert children(_index(tmp_path, body)) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_assigns_no_arc_from_20_through_28() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children(indexes[-1])
    assert [node.oid for node in nodes] == []
    assert all(node.parent == "2" for node in nodes)
