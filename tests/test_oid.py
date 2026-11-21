"""Root-arc parsing. The fixture is an invented table in the shape of an annex, not a recommendation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.library import root_nodes
from primarysource.oid.tree import FORMAT, document, parse_root_table

_TABLE = """
Primary integer value Resulting label
7 "7" "Gasket" gasket (washer - see Z.1) Administered by the gasket office
8 "8" "Sprocket" sprocket Administered by the sprocket office
9 "9" "Widget" widget (sprocket- widget - see Z.2) Jointly administered
"""


def test_root_table_reads_number_labels_and_synonyms() -> None:
    nodes = parse_root_table(_TABLE, "X.1§A.2.2")
    assert [node.oid for node in nodes] == ["7", "8", "9"]
    assert nodes[0].names == ("gasket", "washer")
    assert nodes[0].unicode_labels == ("7", "Gasket")
    assert nodes[2].names == ("widget", "sprocket-widget")
    assert nodes[0].cite == "X.1§A.2.2"
    assert nodes[0].parent is None


def test_a_clause_without_the_table_is_an_error() -> None:
    with pytest.raises(LibError, match="no root arcs"):
        parse_root_table("This clause discusses arcs in general and assigns none.", "X.1§A.2.2")


def test_imported_x660_yields_the_three_root_arcs() -> None:
    indexes = sorted((collection_home("itu") / "index").glob("X.660-*.sqlite3"))
    if not indexes:
        pytest.skip("X.660 is not indexed")
    nodes = root_nodes(Path(indexes[-1]))
    assert [node.oid for node in nodes] == ["0", "1", "2"]
    assert nodes[0].names[0] == "itu-t"
    assert nodes[1].names == ("iso",)
    assert nodes[2].names[0] == "joint-iso-itu-t"


def test_export_is_oid_node_json() -> None:
    payload = json.loads(document(parse_root_table(_TABLE, "X.1§A.2.2")))
    assert payload["format"] == FORMAT
    assert payload["nodes"][1]["oid"] == "8"
    assert payload["nodes"][1]["names"] == ["sprocket"]
    assert "Gasket office" not in document(parse_root_table(_TABLE, "X.1§A.2.2"))
