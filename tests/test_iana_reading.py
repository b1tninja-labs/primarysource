"""Reading, looking up and searching imported registries, and the collection behind the core's command and server."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from cursor_check import follow_list, follow_read
from iana_fixture import NAME, install, widgets

from primarysource import cli, registry
from primarysource.errors import LibError
from primarysource.iana import COLLECTION, reader


@pytest.fixture(autouse=True)
def _writable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another test's `--read-only` leaves PRIMARYSOURCE_READONLY in os.environ; these tests need it unset."""
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    install(tmp_path)
    return tmp_path


def test_the_ref_grammar_spells_a_file_a_registry_a_value_and_a_record() -> None:
    parse = reader.parse_ref
    assert parse("dns-parameters") == reader.Target("dns-parameters")
    assert parse("dns-parameters§dns-parameters-4") == reader.Target("dns-parameters", "dns-parameters-4")
    assert parse("dns-parameters::dns-parameters-4¶2") == reader.Target("dns-parameters", "dns-parameters-4", None, 2)
    assert parse("bgp-parameters§bgp-parameters-2#14") == reader.Target("bgp-parameters", "bgp-parameters-2", "14")
    assert parse("bgp-parameters§bgp-parameters-2#6-255") == reader.Target(
        "bgp-parameters", "bgp-parameters-2", "6-255"
    )
    assert parse("stun-parameters§stun-parameters-4#0x8022").value == "0x8022"
    # IANA's own URL fragment names the registry; the prefix is optional
    assert parse("iana:dns-parameters#dns-parameters-4") == reader.Target("dns-parameters", "dns-parameters-4")
    assert parse("IANA:dns-parameters") == reader.Target("dns-parameters")
    assert reader.format_ref("a", "b", "3", 4) == "a§b#3¶4"


@pytest.mark.parametrize("bad", ["", "§x", "¶3", "dns-parameters:1-5", "DNS Parameters", "a§b c"])
def test_a_malformed_ref_is_refused_with_a_hint(bad: str) -> None:
    with pytest.raises(LibError) as caught:
        reader.parse_ref(bad)
    assert caught.value.hint


def test_the_grammar_is_the_collections_and_it_round_trips() -> None:
    parsed = COLLECTION.grammar.parse("demo-widgets§demo-widgets-1#10¶2")
    assert (parsed.doc, parsed.section, parsed.anchor, parsed.para) == ("demo-widgets", "demo-widgets-1", "10", 2)
    assert COLLECTION.grammar.format(parsed) == "demo-widgets§demo-widgets-1#10¶2"


def test_reading_a_file_lists_its_registries_with_the_refs_that_read_them(home: Path) -> None:
    text = reader.read(NAME)
    assert f"{NAME}§{NAME}-1  Widget Message Types  (5 records)" in text
    assert f"  {NAME}§{NAME}-sub  Widget Subflags  (1 records)" in text
    assert "source: https://www.iana.org/assignments/demo-widgets" in text
    assert 'cite: IANA, "Widget Protocol Parameters"' in text and "file updated 2031-02-03" in text


def test_reading_a_registry_gives_its_procedure_notes_ranges_and_records(home: Path) -> None:
    text = reader.read(f"{NAME}§{NAME}-1")
    assert "registration procedure: Standards Action" in text
    assert "range 0-9 (hex 0x00-0x09): Standards Action; core types" in text
    assert "note: Values above 200 follow [RFC9902, Section 3.1]" in text
    assert (
        "¶2 value: 1 | name: HELLO | description: says hello to a gadget | refs: RFC9901, Section 4.2, Ada Example"
        in text
    )
    assert f"source: https://www.iana.org/assignments/{NAME}#{NAME}-1" in text
    assert "span: sha256:" in text and "unit: record" in text
    assert reader.read(f"iana:{NAME}#{NAME}-1") == text


def test_a_registry_pages_by_whole_records_and_next_resumes_without_loss(home: Path) -> None:
    bodies, refs = follow_read(lambda ref: reader.read(ref, max_tokens=20), f"{NAME}§{NAME}-1")
    seen = [line for body in bodies for line in body.splitlines() if line.startswith("¶")]
    assert [line.split()[0] for line in seen] == ["¶1", "¶2", "¶3", "¶4", "¶5"]
    assert all(ref.startswith(f"{NAME}§{NAME}-1¶") for ref in refs[1:])
    listing = reader.read(NAME).split("\n\ncite: ")[0].split("\n\n", 1)[1]
    bodies, refs = follow_read(lambda ref: reader.read(ref, max_tokens=1), NAME)
    assert refs[1] == f"{NAME}¶2" and "\n".join(b.split("\n\n", 1)[1] for b in bodies) == listing


def test_a_value_ref_finds_the_record_including_ranges_and_hex(home: Path) -> None:
    assert "¶3 value: 010 | name: FROB" in reader.read(f"{NAME}§{NAME}-1#10")
    assert "name: Unassigned" in reader.read(f"{NAME}§{NAME}-1#150")
    out = reader.read(f"{NAME}§{NAME}-1#200")
    assert "name: VENDOR" in out and f"value 0xC8, https://www.iana.org/assignments/{NAME}#{NAME}-1" in out


def test_a_value_with_no_record_is_a_plain_statement_not_an_error(home: Path) -> None:
    out = reader.read(f"{NAME}§{NAME}-1#250")
    assert out.startswith("no record in demo-widgets-1 has value '250'")


def test_a_paragraph_ref_is_the_nth_record_and_out_of_range_is_refused(home: Path) -> None:
    out = reader.read(f"{NAME}§{NAME}-1¶2", max_tokens=1)
    assert out.startswith("¶2 ") and "name: HELLO" in out and ", value 1, https://" in out
    assert reader.read(f"{NAME}§{NAME}-1¶2").startswith("¶2 ")  # a ¶ read runs on from that record
    assert reader.parse_ref(f"{NAME}¶3") == reader.Target(NAME, None, None, 3)  # the listing, from registry 3
    with pytest.raises(LibError, match="has 5 records") as caught:
        reader.read(f"{NAME}§{NAME}-1¶6")
    assert NAME in caught.value.hint


def test_an_unknown_registry_names_where_to_look(home: Path) -> None:
    with pytest.raises(LibError, match="no registry 'nope'") as caught:
        reader.read(f"{NAME}§nope")
    assert caught.value.hint == f"read {NAME} to list them with their refs"


def test_a_registry_that_is_not_imported_says_how_to_import_it(home: Path) -> None:
    with pytest.raises(LibError, match="is not imported") as caught:
        reader.read("dns-parameters")
    assert caught.value.action == "primarysource iana import dns-parameters"
    assert caught.value.hint == "iana_list shows the catalogue and what is imported"


def test_lookup_by_number_range_hex_and_text(home: Path) -> None:
    out = reader.lookup(f"{NAME}§{NAME}-1", "1")
    expected = (
        "value: 1 | name: HELLO | description: says hello to a gadget | refs: RFC9901, Section 4.2, Ada Example"
    )
    assert out.splitlines()[0] == f"{NAME}§{NAME}-1¶2  Widget Message Types: {expected}"
    assert "name: Unassigned" in reader.lookup(f"{NAME}§{NAME}-1", "0x64")
    assert "name: VENDOR" in reader.lookup(f"{NAME}§{NAME}-1", "0xc8")
    assert "name: FROB" in reader.lookup(f"{NAME}§{NAME}-1", "frob")  # exact, on a column, ignoring case
    assert "cite: IANA" in out and "value 1" in out


def test_lookup_in_a_whole_file_tries_every_registry(home: Path) -> None:
    out = reader.lookup(NAME, "65535")
    assert f"{NAME}§{NAME}-sub¶1" in out and "name: ALL" in out


def test_lookup_with_no_match_is_text_and_bad_input_is_an_error(home: Path) -> None:
    assert reader.lookup(f"{NAME}§{NAME}-1", "9999").startswith("no record has value '9999'")
    with pytest.raises(LibError):
        reader.lookup(f"{NAME}§{NAME}-1", "  ")
    with pytest.raises(LibError):
        reader.lookup(f"{NAME}§{NAME}-1", "x" * 201)


def test_search_matches_every_word_across_title_and_columns_and_pages(home: Path) -> None:
    out = reader.search("gizmo quiesce")
    assert out.splitlines()[0].startswith(f"{NAME}§{NAME}-2¶1  Widget Flags: bit: bit 3 | flag: QZ")
    assert "no record matches" in reader.search("quiesce frob")
    many = reader.search("widget", limit=2)
    assert len([ln for ln in many.splitlines() if "§" in ln]) == 2 and "next: start=2" in many
    rest = reader.search("widget", limit=2, start=2)
    assert "next: start=4" in rest
    every = reader.search("widget", limit=500).split("\n\n")[0].split("\n")
    assert [r for r in follow_list(lambda s: reader.search("widget", limit=2, start=s)) if "§" in r] == every
    assert reader.search("rfc9901", file=NAME).count("\n") >= 3
    with pytest.raises(LibError):
        reader.search("")


def test_search_with_nothing_imported_names_the_import_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    with pytest.raises(LibError, match="no registry is imported") as caught:
        reader.search("anything")
    assert "primarysource iana import" in caught.value.action


def test_a_file_that_differs_from_its_recorded_sha256_is_flagged(home: Path) -> None:
    path = home / "iana" / f"{NAME}.xml"
    path.write_bytes(path.read_bytes().replace(b"HELLO", b"HELLX"))
    assert "warning: the file differs from the sha256 recorded" in reader.read(f"{NAME}§{NAME}-1")
    assert "files differ from their recorded sha256" in reader.search("hellx")


def test_a_file_with_no_manifest_entry_is_flagged_and_hostile_xml_is_refused_on_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    install(tmp_path, manifest=False)
    assert "no manifest entry" in reader.read(NAME)
    evil = b'<!DOCTYPE registry [<!ENTITY a "x">]><registry xmlns="http://www.iana.org/assignments" id="demo-evil"/>'
    install(tmp_path, "demo-evil", body=evil, manifest=False)
    with pytest.raises(LibError, match="document type declarations"):
        reader.read("demo-evil")


def test_the_listing_marks_what_is_imported_with_its_updated_date_and_digest(home: Path) -> None:
    out = reader.listing()
    assert "dns-parameters  " in out and "[not imported]" in out
    assert f"{NAME}  (not in the catalogue)  [imported]" in out


def test_the_collection_loads_through_the_registry_and_its_command_runs(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert registry.load("iana") is COLLECTION and COLLECTION.prefix == "iana_"
    assert cli.main(["iana", "lookup", f"{NAME}§{NAME}-1", "1"]) == 0
    assert "name: HELLO" in capsys.readouterr().out
    assert cli.main(["iana", "read", f"{NAME}§{NAME}-1¶2"]) == 0
    assert "name: HELLO" in capsys.readouterr().out
    assert cli.main(["iana", "search", "gizmo"]) == 0
    assert "Widget Flags" in capsys.readouterr().out
    assert cli.main(["iana", "list"]) == 0
    assert cli.main(["iana", "read", "dns-parameters"]) == 1
    assert "primarysource iana import dns-parameters" in capsys.readouterr().err


def test_the_command_imports_through_the_transport_and_refuses_a_fast_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from iana_fixture import FakeIana

    from primarysource.iana import importer

    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    monkeypatch.setattr(importer, "urllib_transport", FakeIana({NAME: widgets()}))
    from primarysource.iana import cli as iana_cli

    assert iana_cli.main(["import", NAME]) == 0
    assert f"{NAME}: fetched, updated 2031-02-03" in capsys.readouterr().out
    assert iana_cli.main(["import", NAME, "--interval", "0.1"]) == 1
    assert "under 1 second" in capsys.readouterr().err


def test_the_server_offers_prefixed_tools_and_a_failure_is_a_tool_error(home: Path) -> None:
    pytest.importorskip("mcp")
    server = registry.attribute(COLLECTION, COLLECTION.server, "server")
    assert [t.name for t in asyncio.run(server.list_tools())] == [
        "iana_read",
        "iana_lookup",
        "iana_search",
        "iana_list",
    ]
    result = asyncio.run(server.call_tool("iana_lookup", {"registry": f"{NAME}§{NAME}-1", "value": "1"}))
    assert "name: HELLO" in str(result)
    with pytest.raises(Exception, match="primarysource iana import dns-parameters"):
        asyncio.run(server.call_tool("iana_read", {"ref": "dns-parameters"}))


def test_the_collection_grammar_is_the_real_parser() -> None:
    grammar = COLLECTION.grammar
    for text in ("widgets", "widgets§widgets-1", "widgets§widgets-1#3", "widgets§widgets-1¶4"):
        assert grammar.format(grammar.parse(text)) == text
    assert grammar.format(grammar.parse("iana:widgets#widgets-1")) == "widgets§widgets-1"
    with pytest.raises(LibError):
        grammar.parse("§widgets-1")
