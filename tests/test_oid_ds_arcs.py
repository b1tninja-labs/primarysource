"""Arcs assigned directly under 2.5. The fixture is invented text."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.ds_arcs import children

_BODY = """
gasket ID ::= {ds gasket(4)}
sprocket ID ::= {ds 7}
washer ID ::= {ds 4}
rivet ID ::= {ds 4 3}
pinion ID ::= {gasket 3}
bolt ID ::= {ds(5) module(1) bolt(9)}
EXAMPLE: flange ID ::= {ds 3}
-- cam ID ::= {ds 8}
"""

_IMPORTED = (
    ("2.5.1", ("module",)),
    ("2.5.2", ("serviceElement",)),
    ("2.5.3", ("applicationContext", "id-ac")),
    ("2.5.4", ("attributeType", "id-at")),
    ("2.5.5", ("attributeSyntaxVendor",)),
    ("2.5.6", ("objectClass", "id-oc")),
    ("2.5.8", ("algorithm",)),
    ("2.5.9", ("abstractSyntax", "id-as")),
    ("2.5.12", ("dsaOperationalAttribute", "id-doa")),
    ("2.5.13", ("matchingRule", "id-mr")),
    ("2.5.14", ("knowledgeMatchingRule", "id-kmr")),
    ("2.5.15", ("nameForm", "id-nf")),
    ("2.5.16", ("group",)),
    ("2.5.17", ("subentry", "id-sc")),
    ("2.5.18", ("operationalAttributeType", "id-oa")),
    ("2.5.19", ("operationalBinding", "id-ob")),
    ("2.5.20", ("schemaObjectClass", "id-soc")),
    ("2.5.21", ("schemaOperationalAttribute", "id-soa")),
    ("2.5.23", ("administrativeRoles", "id-ar")),
    ("2.5.24", ("accessControlAttribute", "id-aca")),
    ("2.5.28", ("accessControlSchemes", "id-acScheme")),
    ("2.5.29", ("certificateExtension", "id-ce")),
    ("2.5.30", ("managementObject", "id-mgt")),
    ("2.5.31", ("attributeValueContext", "id-avc")),
    ("2.5.33", ("idmProtocol", "id-idm")),
    ("2.5.34", ("problem", "id-pr")),
    ("2.5.35", ("notification", "id-not")),
    ("2.5.36", ("matchingRestriction", "id-mre")),
    ("2.5.37", ("controlAttributeType", "id-cat")),
    ("2.5.38", ("keyPurposes", "id-kp")),
    ("2.5.39", ("passwordQuality", "id-pq")),
    ("2.5.40", ("attributeSyntax", "id-ats", "id-asx")),
    ("2.5.41", ("avRestriction", "id-avr")),
    ("2.5.42", ("cmsContentType", "id-cmsct")),
)


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


def test_one_arc_assignments_become_children(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, _BODY))
    assert [node.oid for node in nodes] == ["2.5.4", "2.5.7"]
    assert [node.names for node in nodes] == [("gasket", "washer"), ("sprocket",)]
    assert nodes[0].unicode_labels == ("4",)
    assert nodes[1].unicode_labels == ("7",)
    assert nodes[0].parent == "2.5"
    assert nodes[1].parent == "2.5"
    assert nodes[0].cite == "X.9§Z.4"
    dropped = {"rivet", "pinion", "bolt", "flange", "cam"}
    assert dropped.isdisjoint({name for node in nodes for name in node.names})


def test_the_same_number_unions_names_and_keeps_the_first_cite(tmp_path: Path) -> None:
    path = tmp_path / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            (("A.1", "gasket ID ::= {ds 4}"), ("B.2", "sprocket ID ::= {ds 4}")),
        )
    nodes = children(path)
    assert len(nodes) == 1
    assert nodes[0].oid == "2.5.4"
    assert nodes[0].names == ("gasket", "sprocket")
    assert nodes[0].cite == "X.9§A.1"
    assert nodes[0].parent == "2.5"


def test_a_name_that_points_at_an_arc_joins_it(tmp_path: Path) -> None:
    body = "gasket ID ::= {ds 4}\nsprocket ID ::= gasket\n-- cam ID ::= gasket\n"
    nodes = children(_index(tmp_path, body))
    assert [node.oid for node in nodes] == ["2.5.4"]
    assert nodes[0].names == ("gasket", "sprocket")


def test_nothing_assigned_is_empty(tmp_path: Path) -> None:
    body = "rivet ID ::= {ds 4 3}\nEXAMPLE: flange ID ::= {ds 1}\n-- cam ID ::= {ds 8}"
    assert children(_index(tmp_path, body)) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.501-2099-01.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_arcs_directly_under_ds() -> None:
    index = collection_home("itu") / "index" / "X.501-2019-10.sqlite3"
    if not index.is_file():
        pytest.skip("X.501 is not indexed")
    nodes = children()
    assert [(node.oid, node.names) for node in nodes] == list(_IMPORTED)
    assert {node.parent for node in nodes} == {"2.5"}
    assert {node.cite for node in nodes} == {"X.501§31.1.9"}
    assert all(node.unicode_labels == (node.oid.rsplit(".", 1)[1],) for node in nodes)
    assert all(node.oid.count(".") == 2 for node in nodes)
