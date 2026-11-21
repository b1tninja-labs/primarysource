"""Invented OID assignments, and the arcs this batch of free ISO documents allocates."""

from __future__ import annotations

from pathlib import Path

import pytest

from primarysource.home import collection_home
from primarysource.oid.free_iso_10k import children, covered, parse_assignments

_DOCS: tuple[str, ...] = (
    "10000-1@1998",
    "10000-2@1998",
    "10000-3@1998",
    "10032@2003",
    "10090@1992",
    "10149@1995",
    "10176@2003",
    "10182@2016",
    "10822-1@2025",
    "11017@1998",
    "11172-5@1998",
    "12785-3@2012",
    "12860@2009",
    "12861@2009",
    "13818-5@2005",
    "14369@2018",
    "14475@2001",
    "15938-11@2005",
    "15942@2000",
    "15944-6@2015",
)

_FRAGMENT = """
gasket OBJECT IDENTIFIER ::= { sprocket(1) gasket(4) }
sprocket OBJECT IDENTIFIER ::= { gasket 2 }
"""

_NOT_AN_ASSIGNMENT = """
Corresponds to ITU-T Recommendation X.660.
EXAMPLE: 1.2.3.4
gasket(4) labels a figure.
"""


def _extracts() -> Path | None:
    directory = collection_home("iso") / "extracted"
    if directory.is_dir():
        return directory
    return None


def test_parse_assignments_reads_a_name_number_path() -> None:
    nodes = parse_assignments(_FRAGMENT, "iso:9@2000§Z.1")
    assert [(node.oid, node.parent, node.names) for node in nodes] == [
        ("1.4", "1", ("gasket",)),
        ("1.4.2", "1.4", ("sprocket",)),
    ]
    assert nodes[0].cite == "iso:9@2000§Z.1"
    assert nodes[0].unicode_labels == ()
    assert nodes[1].unicode_labels == ()


def test_a_bibliographic_mention_and_an_example_assign_nothing() -> None:
    assert parse_assignments(_NOT_AN_ASSIGNMENT, "iso:9@2000§Z.1") == ()
    assert parse_assignments("", "iso:9@2000§Z.1") == ()


def test_an_example_hides_a_later_assignment() -> None:
    hidden = "EXAMPLE: gasket OBJECT IDENTIFIER ::= { sprocket(1) gasket(4) }"
    assert parse_assignments(hidden, "iso:9@2000§Z.1") == ()


def test_covered_matches_extracts_that_exist() -> None:
    directory = _extracts()
    if directory is None:
        pytest.skip("ISO extract directory is missing")
    present = tuple(doc for doc in _DOCS if (directory / f"{doc.replace('@', '_')}.json").is_file())
    assert covered() == present


def test_these_documents_assign_no_arcs() -> None:
    if _extracts() is None:
        pytest.skip("ISO extract directory is missing")
    assert children() == ()
