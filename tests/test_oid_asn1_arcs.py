"""Arcs under asn1(1). The fixture is invented assignment text, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.asn1_arcs import children

_BODY = """
hub OBJECT IDENTIFIER ::= {joint-iso-itu-t(2) asn1(1) gasket(4)}
sprocket OBJECT IDENTIFIER ::= {joint- iso-itu-t asn1(1) gasket(4) sprocket(7)}
washer OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) gasket(4) sprocket(7) washer(3)}
rivet OBJECT IDENTIFIER ::= {joint-iso-itu-t rivet(8)}
flange OBJECT IDENTIFIER ::= {joint-iso-itu-t example(999) flange(2)}
The transfer syntax is identified by {joint-iso-itu-t asn1(1) cog(6)}.
EXAMPLE: pinion OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) pinion(3)}
"""


def _write(directory: Path, name: str, sections: dict[str, str]) -> None:
    path = directory / name
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            list(sections.items()),
        )


def test_an_assignment_keeps_the_child_and_one_named_grandchild(tmp_path: Path) -> None:
    _write(tmp_path, "X.680-2021-02.sqlite3", {"12.1": _BODY})
    nodes = children(tmp_path)
    assert [(node.oid, node.names, node.parent) for node in nodes] == [
        ("2.1", ("asn1",), "2"),
        ("2.1.4", ("gasket",), "2.1"),
        ("2.1.4.7", ("sprocket",), "2.1.4"),
    ]
    assert [node.unicode_labels for node in nodes] == [("1",), ("4",), ("7",)]
    assert {node.cite for node in nodes} == {"X.680§12.1"}
    dropped = {"hub", "washer", "rivet", "flange", "cog", "pinion"}
    assert dropped.isdisjoint({name for node in nodes for name in node.names})


def test_a_bare_number_keeps_its_place(tmp_path: Path) -> None:
    body = "cog OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) 4 sprocket(7) washer(1)}"
    _write(tmp_path, "X.680-2021-02.sqlite3", {"9": body})
    nodes = children(tmp_path)
    assert [(node.oid, node.names, node.parent) for node in nodes] == [
        ("2.1", ("asn1",), "2"),
        ("2.1.4", (), "2.1"),
        ("2.1.4.7", ("sprocket",), "2.1.4"),
    ]


def test_earlier_clauses_modules_and_prose_assign_arcs(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "X.680-2021-02.sqlite3",
        {
            "12.10": "cog OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) gasket(4) cog(1)}",
            "4.2": "gasket OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) gasket(4)}",
            "B.1": "Values are assigned: { joint-iso-itu-t asn1(1) hoop(5) sprocket(1) washer(9) }",
            "C.1": "WidgetModule {joint-iso-itu-t asn1(1) widget(9) sprocket(2)} DEFINITIONS ::= BEGIN",
        },
    )
    nodes = children(tmp_path)
    assert [(node.oid, node.names, node.cite) for node in nodes] == [
        ("2.1", ("asn1",), "X.680§4.2"),
        ("2.1.4", ("gasket",), "X.680§4.2"),
        ("2.1.4.1", ("cog",), "X.680§12.10"),
        ("2.1.5", ("hoop",), "X.680§B.1"),
        ("2.1.5.1", ("sprocket",), "X.680§B.1"),
        ("2.1.9", ("widget",), "X.680§C.1"),
        ("2.1.9.2", ("sprocket",), "X.680§C.1"),
    ]


def test_the_current_edition_and_the_earlier_recommendation_win(tmp_path: Path) -> None:
    _write(
        tmp_path, "X.680-2002-07.sqlite3", {"1": "washer OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) washer(3)}"}
    )
    _write(
        tmp_path, "X.680-2021-02.sqlite3", {"8": "gasket OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) gasket(4)}"}
    )
    _write(
        tmp_path,
        "X.681-2021-02.sqlite3",
        {"3": "sprocket OBJECT IDENTIFIER ::= {joint-iso-itu-t asn1(1) gasket(4) sprocket(8)}"},
    )
    _write(tmp_path, "X.683-2021-02.sqlite3", {"A.1": "EXAMPLE: {joint-iso-itu-t asn1(1) flange(9)}"})
    nodes = children(tmp_path)
    assert [(node.oid, node.names, node.cite) for node in nodes] == [
        ("2.1", ("asn1",), "X.680§8"),
        ("2.1.4", ("gasket",), "X.680§8"),
        ("2.1.4.8", ("sprocket",), "X.681§3"),
    ]


def test_nothing_assigned_is_empty(tmp_path: Path) -> None:
    _write(tmp_path, "X.682-2021-02.sqlite3", {"1": "No number is given here."})
    assert children(tmp_path) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_asn1_arcs() -> None:
    index = collection_home("itu") / "index" / "X.680-2021-02.sqlite3"
    if not index.is_file():
        pytest.skip("X.680 is not indexed")
    nodes = children()
    assert [(node.oid, node.names, node.parent, node.cite) for node in nodes] == [
        ("2.1", ("asn1",), "2", "X.680§41.3"),
        ("2.1.0", ("specification",), "2.1", "X.680§41.3"),
        ("2.1.0.0", ("modules",), "2.1.0", "X.680§42.1.1"),
        ("2.1.0.1", ("characterStrings",), "2.1.0", "X.680§41.3"),
        ("2.1.1", ("basic-encoding",), "2.1", "X.680§D.2"),
        ("2.1.2", ("ber-derived",), "2.1", "X.680§D.2"),
        ("2.1.2.0", ("canonical-encoding",), "2.1.2", "X.680§D.2"),
        ("2.1.2.1", ("distinguished-encoding",), "2.1.2", "X.680§D.2"),
        ("2.1.3", ("packed-encoding",), "2.1", "X.680§D.2"),
        ("2.1.3.0", ("basic",), "2.1.3", "X.680§D.2"),
        ("2.1.3.1", ("canonical",), "2.1.3", "X.680§D.2"),
        ("2.1.5", ("xml-encoding",), "2.1", "X.680§D.2"),
        ("2.1.5.0", ("basic",), "2.1.5", "X.680§D.2"),
        ("2.1.5.1", ("canonical",), "2.1.5", "X.680§D.2"),
        ("2.1.5.2", ("extended",), "2.1.5", "X.680§D.2"),
    ]
    assert all(node.unicode_labels == (node.oid.rsplit(".", 1)[-1],) for node in nodes)
    absent = {"2.1.0.0.0", "2.1.0.0.1", "2.1.0.0.3", "2.1.0.1.0", "2.1.3.0.0", "2.1.123"}
    assert absent.isdisjoint({node.oid for node in nodes})
