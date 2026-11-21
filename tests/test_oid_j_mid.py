"""Arcs 2.10 through 2.19 under joint-iso-itu-t. The fixture is invented text, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.j_mid import children

_SPROCKET = """
An arc beneath joint-iso-itu-t has been allocated to the washer bench, with a primary integer value of 12
and a non-integer Unicode label of "Sprocket" and a secondary identifier of sprocket.
Rows under that arc: 1 "1" cog 18 "18" pinion
"""

_GASKET = """
The bench record is {joint-
iso-itu-t(2) gasket(16)} and the IRI "/Joint-ISO-ITU-T/Gasket".
{joint-iso-itu-t(2) widget(9)} is outside this band.
"""

_FLANGE = """
An arc beneath joint-iso-itu-t has been allocated to the scrap bin, with a primary integer value of 4
and a non-integer Unicode label of "Flange" and a secondary identifier of flange.
"""


def _index(directory: Path, bodies: dict[str, str]) -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            list(bodies.items()),
        )
    return path


def test_assigned_arcs_in_range_skip_subordinate_rows_and_the_rest(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"A.9": _SPROCKET, "A.1": _GASKET, "A.3": _FLANGE}))
    assert [node.oid for node in nodes] == ["2.12", "2.16"]
    assert [node.names for node in nodes] == [("sprocket",), ("gasket",)]
    assert nodes[0].unicode_labels == ("12", "Sprocket")
    assert nodes[1].unicode_labels == ("16", "Gasket")
    assert nodes[0].parent == "2"
    assert nodes[1].parent == "2"
    assert nodes[0].cite == "X.9§A.9"
    assert nodes[1].cite == "X.9§A.1"
    absent = {name for node in nodes for name in node.names}
    assert "flange" not in absent
    assert "cog" not in absent
    assert "pinion" not in absent
    assert "widget" not in absent


def test_nothing_in_range_is_empty(tmp_path: Path) -> None:
    bodies = {"B.1": _FLANGE, "B.2": '1 "1" gasket\n18 "18" sprocket\n'}
    assert children(_index(tmp_path, bodies)) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.660-2011-07.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_x660_mid_joint_arcs() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = children(indexes[-1])
    assert [node.oid for node in nodes] == ["2.16", "2.17"]
    assert [node.names for node in nodes] == [("country",), ("registration-procedures",)]
    assert [node.cite for node in nodes] == ["X.660§A.5.5", "X.660§A.5.4"]
    assert [node.unicode_labels for node in nodes] == [
        ("16", "Country"),
        ("17", "Registration_Procedures"),
    ]
    assert all(node.parent == "2" for node in nodes)
