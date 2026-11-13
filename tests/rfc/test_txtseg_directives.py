"""Fallback txt segmentation (primarysource.rfc.index.txtseg) for Legacy RFCs. Ported from rfclib's uncommitted work.

Documents with no machine-readable table of contents fall back to the
left-margin successor scan -- the only path that runs a candidate title through
`_clean_title`'s case gate (ToC-backed docs take their titles from the ToC, so
they were never affected: RFC 1714 anchors 84/84 that way).

Legacy RFCs title subsections after a bare lowercase directive name -- RFC 2167
"3.3.5 holdconnect" -- which the gate used to discard, collapsing the whole
directives section into its parent §3.3 and mislabelling every directive quote.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from primarysource.rfc.index import chunker, txtseg

RFC2167 = Path(os.environ.get("RFCLIB_HOME", "/nonexistent")) / "mirror" / "rfc" / "rfc2167.txt"


def _legacy_doc(extra: list[str] | None = None) -> list[str]:
    """A pre-1998-style txt RFC: no ToC, indented body paragraphs.

    Numbering follows a chain the outline rule accepts (siblings, and a first
    child only at .1), so a failure below means titles, not numbering.
    """
    lines = [
        "Network Working Group                                          J. Doe",
        "Request for Comments: 2167                                        XYZ",
        "Category: Experimental                                  March 1997",
        "",
        "",
        "1.  Introduction",
        "",
        "   This memo describes a protocol for querying directory services.",
        "",
        "2.  Overview",
        "",
        "   The protocol is a superset of the earlier one.",
        "",
        "3.  The RWhois Protocol",
        "",
        "   This section defines the protocol elements.",
        "",
        "3.1  Client/Server Interaction",
        "",
        "   The client opens a connection and sends queries.",
        "",
        "3.2  Query Mechanics",
        "",
        "   A query names a class and one or more attributes.",
        "",
        "3.3  Protocol Directives",
        "",
        "   Directives modify the query. They appear in the query stream.",
        "",
        "3.3.1 class",
        "",
        "   The class of the query is either 'other' or a known class.",
        "",
        "3.3.2 directive",
        "",
        "   The directive line modifies how the server answers.",
        "",
        "3.3.3 holdconnect",
        "",
        "   By default, the holdconnect state must be set to \"off\".",
        "",
    ]
    lines += extra or []
    return lines


def _sections(lines: list[str]) -> dict[str, str]:
    heads, _quality, _bounds = txtseg.find_headings(lines)
    return {num: title for _line, num, title in heads}


def test_legacy_doc_uses_the_fallback_scan():
    # Guards the premise of the tests below: this input must take the scan path.
    _heads, quality, _bounds = txtseg.find_headings(_legacy_doc())
    assert quality.method == "scan"


def test_lowercase_directive_subsections_are_kept_with_their_titles():
    sections = _sections(_legacy_doc())
    assert sections.get("3.3.1") == "class"
    assert sections.get("3.3.2") == "directive"
    assert sections.get("3.3.3") == "holdconnect"
    # The body text a caller reads must land under the directive, not the parent.
    assert sections.get("3.3") == "Protocol Directives"


def test_runon_lowercase_prose_is_still_not_a_title():
    lines = _legacy_doc(
        [
            "3.3.4 the server must then return the objects it holds",
            "",
            "   More prose that is clearly not a section title.",
            "",
        ]
    )
    assert "3.3.4" not in _sections(lines)


def test_clean_title_widens_only_single_lowercase_tokens():
    assert chunker._clean_title("holdconnect") is None  # unchanged default
    assert chunker._clean_title("holdconnect", allow_lowercase=True) == "holdconnect"
    assert chunker._clean_title("client/server", allow_lowercase=True) == "client/server"
    for prose in ("the server must reply", "holdconnect is off", "objects, in order"):
        assert chunker._clean_title(prose, allow_lowercase=True) is None


def test_titlecase_titles_are_unaffected_by_the_flag():
    for title in ("Introduction", "Query Routing Rules", "Error Codes"):
        assert chunker._clean_title(title) == title
        assert chunker._clean_title(title, allow_lowercase=True) == title


@pytest.mark.skipif(not RFC2167.exists(), reason="needs the local RFC mirror")
def test_rfc2167_directives_are_sections_of_their_own():
    """The regression this exists for: every RFC 2167 directive is addressable.

    Before the fix the directives collapsed into their parent, so 'read
    RFC2167§3.3.5' and any citation of -holdconnect resolved to §3.3. RFC 1714,
    the obsolete predecessor with the same lowercase titles, never needed this:
    it has a machine-readable ToC, and ToC titles bypass the case gate.
    """
    lines = RFC2167.read_text(encoding="utf-8", errors="replace").splitlines()
    sections = _sections(lines)
    assert sections.get("3.3.5") == "holdconnect"
    assert sections.get("3.3.13") == "status"
    assert sections.get("3.2.1") == "rwhois"
    assert all(f"3.3.{i}" in sections for i in range(1, 16))
    # Siblings after the recovered run must not be traded away.
    for sibling in ("3.2", "3.4", "3.5", "3.6", "4", "5"):
        assert sibling in sections
    assert len(sections) >= 60
