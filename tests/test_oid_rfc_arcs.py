"""Parsing of invented OID assignments, and the arcs registered under 0 and 1."""

from __future__ import annotations

import pytest

from primarysource.errors import LibError
from primarysource.oid.rfc_arcs import children, parse_assignments

_FRAGMENT = """
gasket OBJECT IDENTIFIER ::= { sprocket(1) 4 }
sprocket OBJECT IDENTIFIER ::= { gasket 2 }
"""


def test_parse_assignments_reads_a_name_number_path() -> None:
    nodes = parse_assignments(_FRAGMENT, "X.1§9")
    assert [(node.oid, node.parent, node.names) for node in nodes] == [
        ("1.4", "1", ("gasket",)),
        ("1.4.2", "1.4", ("sprocket",)),
    ]
    assert nodes[0].cite == "X.1§9"
    assert nodes[0].unicode_labels == ()
    assert nodes[1].unicode_labels == ()


def test_a_fragment_that_assigns_nothing_is_an_error() -> None:
    with pytest.raises(LibError, match="assigns nothing"):
        parse_assignments("Arcs are discussed here and none is given a number.", "X.1§9")


def test_children_are_the_registered_arcs() -> None:
    nodes = children()
    assert [(node.oid, node.names, node.parent, node.cite) for node in nodes] == [
        ("0.0", ("zeroDotZero",), "0", "RFC2578§2"),
        ("1.3.6.1", ("internet",), "1.3.6", "RFC1155§3.1"),
        ("1.3.6.1.1", ("directory",), "1.3.6.1", "RFC1155§3.1"),
        ("1.3.6.1.2", ("mgmt",), "1.3.6.1", "RFC1155§3.1"),
        ("1.3.6.1.3", ("experimental",), "1.3.6.1", "RFC1155§3.1"),
        ("1.3.6.1.4", ("private",), "1.3.6.1", "RFC1155§3.1"),
        ("1.3.6.1.4.1", ("enterprises",), "1.3.6.1.4", "RFC1155§3.1.4"),
        ("1.3.6.1.5", ("security",), "1.3.6.1", "RFC2578§2"),
        ("1.3.6.1.6", ("snmpV2",), "1.3.6.1", "RFC2578§2"),
        ("1.3.6.1.6.1", ("snmpDomains",), "1.3.6.1.6", "RFC2578§2"),
        ("1.3.6.1.6.2", ("snmpProxys",), "1.3.6.1.6", "RFC2578§2"),
        ("1.3.6.1.6.3", ("snmpModules",), "1.3.6.1.6", "RFC2578§2"),
    ]
    assert all(node.unicode_labels == () for node in nodes)


def test_children_leave_out_uses_examples_and_the_excluded_trees() -> None:
    oids = {node.oid for node in children()}
    assert "1.3" not in oids
    assert "1.3.6" not in oids
    assert "1.3.6.1.2.1" not in oids
    assert "1.3.6.1.2.1.10" not in oids
    assert "1.3.6.1.4.1.42" not in oids
    assert "1.3.6.1.7" not in oids
