"""High free ISO extracts. The fixture is invented assignment text, not a standard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.free_iso_high import children, covered, parse_assignments

_ASSIGNED = """
Allocated OID arc {joint- iso-itu-t(2) gasket(4) sprocket(7)}.
See ITU-T Rec. X.9.
EXAMPLE: {joint-iso-itu-t(2) flange(8)}
The dotted number 2.99 is in the example.
"""

_CHILD = """
gasket OBJECT IDENTIFIER ::= {iso(1) gasket(6) sprocket(1)}
See ITU-T Rec. X.9.
EXAMPLE: {iso(1) flange(3)}
The dotted number 1.2.3 is an example.
"""

_EMPTY = """
See ITU-T Rec. X.660.
gasket(4) labels a figure.
EXAMPLE: {iso(1) gasket(4) sprocket(7)}
The dotted number 1.2.3 is an example.
"""


def _extract(directory: Path, filename: str, doc: str, sections: list[dict[str, object]]) -> None:
    payload = {"doc": doc, "sections": sections}
    (directory / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_an_invented_arc_keeps_gasket_and_sprocket_and_drops_the_example() -> None:
    nodes = parse_assignments(_ASSIGNED, "iso:9@2000§Z.1")
    assert [(node.oid, node.names, node.parent, node.cite, node.unicode_labels) for node in nodes] == [
        ("2.4", ("gasket",), "2", "iso:9@2000§Z.1", ("4",)),
        ("2.4.7", ("sprocket",), "2.4", "iso:9@2000§Z.1", ("7",)),
    ]
    assert all(name != "flange" for node in nodes for name in node.names)
    assert "2.99" not in {node.oid for node in nodes}


def test_a_longer_value_keeps_each_named_arc() -> None:
    nodes = parse_assignments(_CHILD, "iso:9@2000§Z.2")
    assert [(node.oid, node.names, node.parent, node.cite) for node in nodes] == [
        ("1.6", ("gasket",), "1", "iso:9@2000§Z.2"),
        ("1.6.1", ("sprocket",), "1.6", "iso:9@2000§Z.2"),
    ]
    assert all(name != "flange" for node in nodes for name in node.names)


def test_a_mention_and_an_example_assign_nothing() -> None:
    assert parse_assignments(_EMPTY, "iso:9@2000§Z.3") == ()
    assert parse_assignments("", "iso:9@2000§Z.3") == ()


def test_children_read_invented_extracts(tmp_path: Path) -> None:
    _extract(tmp_path, "21890_2001.json", "21890@2001", [{"id": "Z.1", "text": _EMPTY}])
    _extract(tmp_path, "19759_2016.json", "19759@2016", [{"id": "Z.9", "text": _ASSIGNED}])
    _extract(tmp_path, "23272_2011.json", "23272@2011", [{"id": 4, "text": _CHILD}])
    assert covered(tmp_path) == ("19759@2015", "21890@2001", "23272@2011")
    assert [(node.oid, node.names, node.parent, node.cite) for node in children(tmp_path)] == [
        ("1.6", ("gasket",), "1", "iso:23272@2011§4"),
        ("1.6.1", ("sprocket",), "1.6", "iso:23272@2011§4"),
        ("2.4", ("gasket",), "2", "iso:19759@2016§Z.9"),
        ("2.4.7", ("sprocket",), "2.4", "iso:19759@2016§Z.9"),
    ]


def test_a_missing_directory_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "extracted"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_opened_extracts_include_21890_and_19759() -> None:
    directory = collection_home("iso") / "extracted"
    if not directory.is_dir():
        pytest.skip("ISO extract directory is missing")
    found = covered()
    if (directory / "21890_2001.json").is_file():
        assert "21890@2001" in found
    if (directory / "19759_2016.json").is_file():
        assert "19759@2015" in found
    assert children() == ()
