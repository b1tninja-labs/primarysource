"""Merging oid nodes. The fixtures are invented arcs, not text from a recommendation or an RFC."""

from __future__ import annotations

import json

import pytest

from primarysource.errors import LibError
from primarysource.oid.library import export, merge_nodes, read, root_nodes
from primarysource.oid.tree import FORMAT, Node


def test_merge_unions_names_and_sorts_by_integer_tuple() -> None:
    first = Node(oid="1.3", names=("alpha", "beta"), unicode_labels=("one",), cite="src-a", parent="1")
    again = Node(oid="1.3", names=("beta", "gamma"), unicode_labels=("two",), cite="src-b", parent="9")
    child = Node(oid="1.3.6.1", names=("delta",), unicode_labels=(), cite="src-c", parent=None)
    child_again = Node(
        oid="1.3.6.1",
        names=("epsilon", "delta"),
        unicode_labels=("e",),
        cite="src-d",
        parent="1.3.6",
    )
    wide = Node(oid="2.16", names=("wide",), unicode_labels=(), cite="src-e", parent="2")
    narrow = Node(oid="2.5", names=("narrow",), unicode_labels=(), cite="src-f", parent="2")
    root = Node(oid="1", names=("rootish",), unicode_labels=(), cite="src-g", parent=None)
    merged = merge_nodes([first, wide, again, child, narrow, child_again, root])
    assert [node.oid for node in merged] == ["1", "1.3", "1.3.6.1", "2.5", "2.16"]
    by_oid = {node.oid: node for node in merged}
    assert by_oid["1.3"].names == ("alpha", "beta", "gamma")
    assert by_oid["1.3"].cite == "src-a"
    assert by_oid["1.3"].parent == "1"
    assert by_oid["1.3"].unicode_labels == ("one",)
    assert by_oid["1.3.6.1"].names == ("delta", "epsilon")
    assert by_oid["1.3.6.1"].cite == "src-c"
    assert by_oid["1.3.6.1"].parent == "1.3.6"
    assert by_oid["1.3.6.1"].unicode_labels == ()


def test_a_ref_that_is_not_an_oid_names_oid_roots() -> None:
    with pytest.raises(LibError, match="not an oid") as caught:
        read("not-an-oid")
    assert "oid_roots" in caught.value.hint


def _exported_oids(text: str) -> list[str]:
    parsed: object = json.loads(text)
    if not isinstance(parsed, dict):
        raise AssertionError("export is a JSON object")
    assert parsed.get("format") == FORMAT
    raw_nodes = parsed.get("nodes")
    if not isinstance(raw_nodes, list):
        raise AssertionError("export has a nodes list")
    oids: list[str] = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            raise AssertionError("a node is a JSON object")
        oid = item.get("oid")
        if not isinstance(oid, str):
            raise AssertionError("a node oid is a string")
        oids.append(oid)
    return oids


def test_live_export_lists_each_oid_once() -> None:
    try:
        root_nodes()
    except LibError:
        pytest.skip("X.660 is not indexed")
    text = export()
    assert text.strip().endswith("}")
    oids = _exported_oids(text)
    assert oids == sorted(oids, key=lambda oid: tuple(int(part) for part in oid.split(".")))
    assert len(oids) == len(set(oids))
    for oid in ("0", "1", "2", "0.0", "1.0", "1.3.6.1"):
        assert oids.count(oid) == 1
    body = read("oid:1.3.6.1")
    assert body.startswith("1.3.6.1 ")
    assert "\n\ncite: " in body
    with pytest.raises(LibError, match="unknown oid") as caught:
        read("4")
    assert "oid_roots" in caught.value.hint
