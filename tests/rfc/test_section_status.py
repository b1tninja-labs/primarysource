"""A section read says whether its errata change the text, and which
documents update the document being read."""

from __future__ import annotations

import sqlite3

from primarysource.rfc import views
from primarysource.rfc.cite import errata_note


def _errata() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE errata(
             eid INTEGER PRIMARY KEY, doc_id TEXT, status TEXT, section TEXT)"""
    )
    conn.executemany(
        "INSERT INTO errata(eid, doc_id, status, section) VALUES(?,?,?,?)",
        [
            (1, "RFC5280", "Verified", "3.2"),
            (2, "RFC5280", "Held for Document Update", "4.2.1.6"),
            (3, "RFC5280", "Rejected", "4.2.1.6"),
            (4, "RFC5280", "Reported", "6.1.5"),
        ],
    )
    return conn


def test_held_and_rejected_errata_on_a_section_are_not_applied() -> None:
    note = errata_note(_errata(), "RFC5280", "4.2.1.6")
    assert "1 held on this section, not applied" in note
    assert "1 rejected on this section, not applied" in note
    assert "verified" not in note


def test_a_verified_erratum_is_the_one_to_read() -> None:
    note = errata_note(_errata(), "RFC5280", "3.2")
    assert "1 verified on this section, read them before implementing" in note
    assert "errata(ref='RFC5280§3.2', status='all')" in note


def test_a_section_with_no_erratum_stays_quiet() -> None:
    note = errata_note(_errata(), "RFC5280", "1")
    assert note == "errata: 1 verified elsewhere, none on this section"


def test_a_parent_section_does_not_inherit_a_child_erratum() -> None:
    note = errata_note(_errata(), "RFC5280", "4.2")
    assert note == "errata: 1 verified elsewhere, none on this section"


def test_the_read_header_names_the_documents_that_update_this_one() -> None:
    line = views._doc_line(
        None,
        views.Ref(doc="RFC5280", served="RFC5280", sec="4.2.1.6"),
        {
            "title": "profile",
            "current_status": "PROPOSED STANDARD",
            "pub_date": "2008-05",
            "is_current": True,
            "relations": {
                "updates": [],
                "updated_by": ["RFC9598", "RFC9549"],
            },
        },
    )
    assert "current" in line
    assert "updated by RFC9598, RFC9549" in line
