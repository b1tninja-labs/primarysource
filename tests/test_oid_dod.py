"""Parsing of an invented OID assignment, and the dod arc."""

from __future__ import annotations

import pytest

from primarysource.errors import LibError
from primarysource.oid.dod import children, parse_assignments

_FRAGMENT = """
gasket OBJECT IDENTIFIER ::= { sprocket(1) 3 }
sprocket OBJECT IDENTIFIER ::= { gasket 6 }
"""


def test_parse_assignments_reads_a_name_number_path() -> None:
    nodes = parse_assignments(_FRAGMENT, "X.1§9")
    assert [(node.oid, node.parent, node.names) for node in nodes] == [
        ("1.3", "1", ("gasket",)),
        ("1.3.6", "1.3", ("sprocket",)),
    ]
    assert nodes[0].cite == "X.1§9"
    assert nodes[0].unicode_labels == ()
    assert nodes[1].unicode_labels == ()


def test_a_fragment_that_assigns_nothing_is_an_error() -> None:
    with pytest.raises(LibError, match="assigns nothing") as caught:
        parse_assignments("Arcs are discussed here and none is given a number.", "X.1§9")
    assert caught.value.hint


def test_children_are_the_dod_arc() -> None:
    nodes = children()
    assert [(node.oid, node.names, node.parent, node.cite) for node in nodes] == [
        ("1.3.6", ("dod",), "1.3", "RFC2578§2"),
    ]
    assert all(node.unicode_labels == () for node in nodes)


def test_children_leave_out_internet_and_its_descendants() -> None:
    oids = {node.oid for node in children()}
    assert "1.3.6.1" not in oids
    assert all(not oid.startswith("1.3.6.1.") for oid in oids)
