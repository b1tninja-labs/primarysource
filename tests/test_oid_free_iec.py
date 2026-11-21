"""Free IEC publications. The fixture is invented assignment text, not a publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.free_iec import children, covered

_ASSIGNED = """
gasket OBJECT IDENTIFIER ::= { sprocket(1) gasket(4) }
ISO and ITU-T are named beside it. iso(1) itu-t(0)
"""

_ALLOCATED = "The clause allocates sprocket(1) gasket(6)."

_MENTION = """
ISO and ITU-T are named here.
The clause allocates iso(1) and itu-t(0).
gasket(4) appears with no allocation.
"""

_IGNORED = """
-- gasket OBJECT IDENTIFIER ::= { sprocket(1) gasket(4) }
EXAMPLE: sprocket OBJECT IDENTIFIER ::= { sprocket(1) sprocket(5) }
"""


def _write(directory: Path, name: str, doc: str, sections: list[tuple[str, str]]) -> None:
    payload = {"doc": doc, "sections": [{"id": section_id, "text": text} for section_id, text in sections]}
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_an_invented_value_is_one_arc(tmp_path: Path) -> None:
    _write(tmp_path, "9_2000.json", "9@2000", [("Z.1", _ASSIGNED)])
    nodes = children(tmp_path)
    assert [(node.oid, node.parent, node.names, node.unicode_labels, node.cite) for node in nodes] == [
        ("1.4", "1", ("gasket",), ("4",), "iec:9@2000§Z.1"),
    ]
    assert covered(tmp_path) == ("9@2000",)


def test_an_allocated_name_number_is_one_arc(tmp_path: Path) -> None:
    _write(tmp_path, "9_2000.json", "9@2000", [("Z.2", _ALLOCATED)])
    nodes = children(tmp_path)
    assert [(node.oid, node.parent, node.names, node.cite) for node in nodes] == [
        ("1.6", "1", ("gasket",), "iec:9@2000§Z.2"),
    ]


def test_a_mention_assigns_nothing_and_the_document_stays_covered(tmp_path: Path) -> None:
    _write(tmp_path, "9_2000.json", "9@2000", [("Z.1", _MENTION)])
    assert children(tmp_path) == ()
    assert covered(tmp_path) == ("9@2000",)


def test_a_comment_and_an_example_assign_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "9_2000.json", "9@2000", [("Z.1", _IGNORED)])
    assert children(tmp_path) == ()
    assert covered(tmp_path) == ("9@2000",)


def test_an_assignment_before_an_example_is_kept(tmp_path: Path) -> None:
    text = _ASSIGNED + "\nEXAMPLE: sprocket OBJECT IDENTIFIER ::= { sprocket(1) sprocket(5) }\n"
    _write(tmp_path, "9_2000.json", "9@2000", [("Z.1", text)])
    nodes = children(tmp_path)
    assert [node.oid for node in nodes] == ["1.4"]
    assert all("sprocket" not in node.names for node in nodes)


def test_every_invented_document_is_covered(tmp_path: Path) -> None:
    _write(tmp_path, "a.json", "a@1", [("1", _MENTION)])
    _write(tmp_path, "b.json", "b@2", [("2", _ASSIGNED)])
    assert covered(tmp_path) == ("a@1", "b@2")
    assert [(node.oid, node.cite) for node in children(tmp_path)] == [("1.4", "iec:b@2§2")]


def test_a_missing_directory_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "extracted"
    with pytest.raises(LibError, match="not found") as caught:
        covered(missing)
    assert caught.value.hint
    assert caught.value.action
    with pytest.raises(LibError, match="not found"):
        children(missing)


def test_imported_extracts_are_covered() -> None:
    directory = collection_home("iec") / "extracted"
    files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    if not files:
        pytest.skip("IEC extracts are not present")
    docs = covered()
    assert docs
    assert len(docs) == len(files)
    assert children() == ()
