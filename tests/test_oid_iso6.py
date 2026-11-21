"""Arc 1.6. The fixture is invented assignment text, not a recommendation or a register."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.oid.iso6 import children, parse_assignments

_ASSIGNED = """
gasket OBJECT IDENTIFIER ::= { iso(1) gasket(6) }
sprocket OBJECT IDENTIFIER ::= { iso(1) identified-organization(3) dod(6) }
pinion ID ::= { iso(1) pinion(6) cog(1) }
EXAMPLE: flange OBJECT IDENTIFIER ::= { iso(1) flange(6) }
"""

_EMPTY = """
sprocket OBJECT IDENTIFIER ::= { iso(1) identified-organization(3) dod(6) }
washer ID ::= { joint-iso-itu-t asn1(1) widget(6) basic(0) }
syn IA5String ::= {1, 6}
EXAMPLE: flange OBJECT IDENTIFIER ::= { iso(1) flange(6) }
"""


def _index(directory: Path, body: str) -> None:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT, ord INTEGER)")
        connection.execute(
            "INSERT INTO sections (section_id, body, ord) VALUES (?, ?, ?)",
            ("Z.1", body, 0),
        )


def _extract(directory: Path, body: str) -> None:
    payload = {"doc": "9@2000", "sections": [{"id": "Z.1", "text": body}]}
    (directory / "9_2000.json").write_text(json.dumps(payload), encoding="utf-8")


def test_an_invented_assignment_parses_as_arc_1_6() -> None:
    nodes = parse_assignments(_ASSIGNED, "X.9§Z.1")
    assert len(nodes) == 1
    node = nodes[0]
    assert node.oid == "1.6"
    assert node.parent == "1"
    assert node.names == ("gasket",)
    assert node.unicode_labels == ("6",)
    assert node.cite == "X.9§Z.1"


def test_invented_text_with_no_assignment_is_empty() -> None:
    assert parse_assignments(_EMPTY, "X.9§Z.1") == ()
    assert parse_assignments("", "X.9§Z.1") == ()


def test_children_read_an_invented_assignment(tmp_path: Path) -> None:
    itu = tmp_path / "index"
    iso = tmp_path / "extracted"
    itu.mkdir()
    iso.mkdir()
    _index(itu, _ASSIGNED)
    nodes = children(itu, iso)
    assert [(node.oid, node.parent, node.names, node.cite) for node in nodes] == [
        ("1.6", "1", ("gasket",), "X.9§Z.1"),
    ]


def test_children_read_invented_empty_text(tmp_path: Path) -> None:
    itu = tmp_path / "index"
    iso = tmp_path / "extracted"
    itu.mkdir()
    iso.mkdir()
    _extract(iso, _EMPTY)
    _index(itu, _EMPTY)
    assert children(itu, iso) == ()


def test_a_missing_directory_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "index"
    iso = tmp_path / "extracted"
    iso.mkdir()
    with pytest.raises(LibError, match="not found") as caught:
        children(missing, iso)
    assert caught.value.hint
    assert caught.value.action


def test_imported_documents_do_not_assign_arc_1_6() -> None:
    try:
        nodes = children()
    except LibError:
        pytest.skip("ITU or ISO library is not present")
    assert nodes == ()
