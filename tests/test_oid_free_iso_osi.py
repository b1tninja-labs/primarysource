"""Free OSI extracts. The fixture is invented assignment text, not a standard."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.free_iso_osi import children, covered, parse_assignments

_ASSIGNED = """
Allocated OID arc {joint- iso-itu-t(2) gasket(4)}.
The secondary identifier sprocket is a synonym for gasket.
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
::= {1=basic, 2=boxed}
EXAMPLE: {joint-iso-itu-t(2) gasket(4)}
The dotted number 2.4 is an example.
"""


def _extract(directory: Path, doc: str, sections: list[dict[str, object]]) -> None:
    number, year = doc.rsplit("@", 1)
    payload = {"doc": doc, "sections": sections}
    (directory / f"{number}_{year}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_an_invented_arc_keeps_the_synonym_and_drops_the_example() -> None:
    nodes = parse_assignments(_ASSIGNED, "iso:9@2000§Z.1")
    assert [(node.oid, node.names, node.parent, node.cite, node.unicode_labels) for node in nodes] == [
        ("2.4", ("gasket", "sprocket"), "2", "iso:9@2000§Z.1", ("4",)),
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
    _extract(tmp_path, "8072@1996", [{"id": "Z.1", "text": _EMPTY}])
    _extract(
        tmp_path,
        "9834-9@2008",
        [{"id": "Z.4", "text": _ASSIGNED}, {"id": 12, "text": _CHILD}],
    )
    assert covered(tmp_path) == ("8072@1996", "9834-9@2008")
    assert [(node.oid, node.names, node.parent, node.cite) for node in children(tmp_path)] == [
        ("1.6", ("gasket",), "1", "iso:9834-9@2008§12"),
        ("1.6.1", ("sprocket",), "1.6", "iso:9834-9@2008§12"),
        ("2.4", ("gasket", "sprocket"), "2", "iso:9834-9@2008§Z.4"),
    ]


def test_a_missing_directory_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "extracted"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_9834_9_is_covered() -> None:
    path = collection_home("iso") / "extracted" / "9834-9_2008.json"
    if not path.is_file():
        pytest.skip("9834-9_2008.json is missing")
    assert "9834-9@2008" in covered()
    nodes = children()
    if nodes:
        assert all(re.fullmatch(r"\d+(?:\.\d+)+", node.oid) for node in nodes)
