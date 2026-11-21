"""Encoding-rule arcs. The fixture is invented assignment text, not a recommendation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.itu.corpus import home
from primarysource.oid.encoding_arcs import children

_ASSIGNED = """
A bench rule is assigned {joint- iso-itu-t gasket(4) sprocket(2)} "/Gasket/Sprocket".
A module path is assigned {joint-iso-itu-t gasket(4) modules(0) sprocket(8)}.
EXAMPLE: {joint-iso-itu-t flange(9) sprocket(3)}
"""

_MENTION = "A cited value {joint-iso-itu-t gasket(4) tooth(7)} is only a mention."


def _index(directory: Path, sections: dict[str, str]) -> Path:
    path = directory / "X.9-2000-01.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sections (section_id TEXT, body TEXT)")
        connection.executemany(
            "INSERT INTO sections (section_id, body) VALUES (?, ?)",
            list(sections.items()),
        )
    return path


def test_assigned_arcs_keep_the_parent_and_drop_examples(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"4.2": _ASSIGNED, "8.1": _MENTION}))
    assert [(node.oid, node.names, node.parent, node.cite, node.unicode_labels) for node in nodes] == [
        ("2.4", ("gasket",), "2", "X.9§4.2", ("4", "Gasket")),
        ("2.4.2", ("sprocket",), "2.4", "X.9§4.2", ("2", "Sprocket")),
    ]
    assert all(name not in {"flange", "tooth", "modules"} for node in nodes for name in node.names)
    assert "2.4.0.8" not in {node.oid for node in nodes}
    assert "2.9" not in {node.oid for node in nodes}


def test_an_example_assigns_nothing(tmp_path: Path) -> None:
    body = 'EXAMPLE: {joint-iso-itu-t gasket(4) sprocket(2)} "/Gasket/Sprocket"'
    assert children(_index(tmp_path, {"4.2": body})) == ()


def test_a_missing_x690_index_names_the_remedy(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="not found") as caught:
        children(tmp_path)
    assert "X.690-2021-02" in caught.value.message
    assert caught.value.hint
    assert caught.value.action


def test_2021_02_indexes_assign_the_encoding_arcs() -> None:
    anchor = home() / "index" / "X.690-2021-02.sqlite3"
    if not anchor.is_file():
        pytest.skip("X.690-2021-02 is not indexed")
    nodes = children()
    assert [(node.oid, node.names, node.parent, node.cite, node.unicode_labels) for node in nodes] == [
        ("2.1", ("asn1",), "2", "X.690§12.2", ("1", "ASN.1")),
        ("2.1.1", ("basic-encoding",), "2.1", "X.690§12.2", ("1", "Basic-Encoding")),
        ("2.1.2", ("ber-derived",), "2.1", "X.690§12.3", ("2", "BER-Derived")),
        ("2.1.2.0", ("canonical-encoding",), "2.1.2", "X.690§12.3", ("0", "Canonical-Encoding")),
        ("2.1.2.1", ("distinguished-encoding",), "2.1.2", "X.690§12.4", ("1", "Distinguished-Encoding")),
        ("2.1.3", ("packed-encoding",), "2.1", "X.691§33.2", ("3", "Packed-Encoding")),
        ("2.1.3.0", ("basic",), "2.1.3", "X.691§33.2", ("0", "Basic")),
        ("2.1.3.0.0", ("aligned",), "2.1.3.0", "X.691§33.2", ("0", "Aligned")),
        ("2.1.3.0.1", ("unaligned",), "2.1.3.0", "X.691§33.2", ("1", "Unaligned")),
        ("2.1.3.1", ("canonical",), "2.1.3", "X.691§33.2", ("1", "Canonical")),
        ("2.1.3.1.0", ("aligned",), "2.1.3.1", "X.691§33.2", ("0", "Aligned")),
        ("2.1.3.1.1", ("unaligned",), "2.1.3.1", "X.691§33.2", ("1", "Unaligned")),
        ("2.1.5", ("xml-encoding",), "2.1", "X.693§40.2", ("5", "XML-Encoding")),
        ("2.1.5.0", ("basic",), "2.1.5", "X.693§40.2", ("0", "Basic")),
        ("2.1.5.1", ("canonical",), "2.1.5", "X.693§40.2", ("1", "Canonical")),
        ("2.1.5.2", ("extended",), "2.1.5", "X.693§40.2", ("2", "Extended")),
        ("2.1.6", ("oer-encoding",), "2.1", "X.696§32.2", ("6",)),
        ("2.1.6.0", ("basic",), "2.1.6", "X.696§32.2", ("0",)),
        ("2.1.6.1", ("canonical",), "2.1.6", "X.696§32.2", ("1",)),
        ("2.1.7", ("jer-encoding",), "2.1", "X.697§42.2", ("7",)),
    ]
