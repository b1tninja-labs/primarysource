"""Certificate-extension arcs under id-ce. The fixture is invented assignment text."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.oid.x509_ce import children

_EARLY = """
-- pinion OBJECT IDENTIFIER ::= {id-ce 3}
gasket OBJECT IDENTIFIER ::= {id-
ce 4}
sprocket OBJECT IDENTIFIER ::= {id-ce 7}
washer OBJECT IDENTIFIER ::= {id-mr 4}
rivet OBJECT IDENTIFIER ::= {id-ce 4 1}
cog OBJECT IDENTIFIER ::= {id-ce-gasket 2}
EXAMPLE: flange OBJECT IDENTIFIER ::= {id-ce 9}
"""

_LATER = """
sprocket OBJECT IDENTIFIER ::= {id-ce 4}
gasket OBJECT IDENTIFIER ::= {id-ce 4}
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


def test_direct_assignments_union_names_and_skip_the_rest(tmp_path: Path) -> None:
    nodes = children(_index(tmp_path, {"B.2": _LATER, "A.1": _EARLY}))
    assert [node.oid for node in nodes] == ["2.5.29.4", "2.5.29.7"]
    assert [node.names for node in nodes] == [("gasket", "sprocket"), ("sprocket",)]
    assert nodes[0].parent == "2.5.29"
    assert nodes[1].parent == "2.5.29"
    assert nodes[0].cite == "X.9§A.1"
    assert nodes[1].cite == "X.9§A.1"
    assert nodes[0].unicode_labels == ()
    assert nodes[1].unicode_labels == ()
    absent = {name for node in nodes for name in node.names}
    assert "pinion" not in absent
    assert "washer" not in absent
    assert "rivet" not in absent
    assert "cog" not in absent
    assert "flange" not in absent
    assert "2.5.29" not in {node.oid for node in nodes}


def test_comments_and_examples_assign_nothing(tmp_path: Path) -> None:
    body = "-- gasket OBJECT IDENTIFIER ::= {id-ce 4}\nEXAMPLE: sprocket OBJECT IDENTIFIER ::= {id-ce 7}\n"
    assert children(_index(tmp_path, {"A.1": body})) == ()


def test_a_missing_index_names_the_remedy(tmp_path: Path) -> None:
    missing = tmp_path / "X.509-2019-10.sqlite3"
    with pytest.raises(LibError, match="not found") as caught:
        children(missing)
    assert caught.value.hint
    assert caught.value.action


def test_imported_certificate_extensions_when_indexed() -> None:
    path = collection_home("itu") / "index" / "X.509-2019-10.sqlite3"
    if not path.is_file():
        pytest.skip("X.509 is not indexed")
    nodes = children()
    assert any(node.oid.startswith("2.5.29.") for node in nodes)
    assert all(node.parent == "2.5.29" for node in nodes)
    assert all(node.cite.startswith("X.509§") for node in nodes)
    assert all(node.unicode_labels == () for node in nodes)
