"""Identifier index and acronym mining (rfclib.index.lexical)."""

from __future__ import annotations

from primarysource.rfc import views
from primarysource.rfc.index import lexical


def test_identifiers_keep_protocol_tokens_whole():
    text = ("the preferred_address transport parameter, "
            "SETTINGS_INITIAL_WINDOW_SIZE, Sec-WebSocket-Accept, X25519, "
            "KeyUpdate and IPv6; see RFC9000 Section 4.1.3, TLS 1.3")
    assert lexical.identifiers(text) == [
        "preferred_address", "settings_initial_window_size",
        "sec-websocket-accept", "x25519", "keyupdate", "ipv6"]


def test_acronym_must_match_initials():
    m = lexical._match_initials
    assert m("NTP", "using the Network Time Protocol".split()) == \
        ["Network", "Time", "Protocol"]
    assert m("IETF", "the Internet Engineering Task Force".split()) == \
        ["Internet", "Engineering", "Task", "Force"]
    assert m("NTP", "a new transport".split()) is None


def test_on_demand_indexing_fills_the_identifier_index(library):
    conn, paths = library
    assert not lexical.ident_search(conn, "c-wsp rule", 5)
    views.read(conn, "RFC5234", mirror_root=paths.mirror)
    hits = lexical.ident_search(conn, "c-wsp rule", 5)
    assert hits and {h["doc_id"] for h in hits} == {"RFC5234"}


def test_rare_identifiers_weigh_more(library):
    conn, paths = library
    for doc in ("RFC5234", "RFC7405", "RFC8651"):
        views.read(conn, doc, mirror_root=paths.mirror)
    assert lexical.ident_weight(conn, "no identifiers here") == 0.0
    assert lexical.ident_weight(conn, "c-wsp") > 0.0


def test_catalog_init_mines_acronyms(library):
    conn, _ = library
    got = lexical.expansions(conn, "TCP MSS and RFC numbers")
    assert got == {"tcp": "transmission control protocol",
                   "mss": "maximum segment size"}
    assert lexical.expansions(conn, "tcp in lowercase") == {}
