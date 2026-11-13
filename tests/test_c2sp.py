"""c2sp: the pinned importer, the refs and tools, over invented documents. No network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from c2sp_fixture import BASE, COMMIT, DOCS, Clock, catalogue, install, sha, transport

from primarysource import cli, registry
from primarysource.c2sp import C2SP, library
from primarysource.c2sp._fetch import Fetcher, check_url
from primarysource.c2sp.catalogue import HOSTS
from primarysource.c2sp.catalogue import catalogue as packaged_catalogue
from primarysource.c2sp.importer import import_specs, pin_specs
from primarysource.errors import LibError


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return install(tmp_path / "c2sp")


# --- the importer ----------------------------------------------------------------------------------------------


def test_the_importer_writes_verified_files_and_a_record(tmp_path: Path) -> None:
    result = import_specs(tmp_path, cat=catalogue(), transport=transport())
    assert result.commit == COMMIT and sorted(result.files) == ["invented-log", "invented-note"]
    assert (tmp_path / COMMIT / "invented-log.md").read_bytes() == DOCS["invented-log"].encode()
    record = json.loads((tmp_path / COMMIT / "install.json").read_text(encoding="utf-8"))
    assert (
        record["files"]["invented-note"] == sha(DOCS["invented-note"].encode()) and record["licence"] == "CC-BY-4.0"
    )
    assert not list((tmp_path / COMMIT).glob("*.part"))


def test_at_most_one_request_per_second() -> None:
    clock = Clock()
    fetcher = Fetcher(HOSTS, transport(), clock=clock.clock, sleep=clock.sleep)
    for name in DOCS:
        fetcher.get(f"{BASE}{COMMIT}/{name}.md", 10_000)
    assert fetcher.requests == 2 and clock.sleeps == [1.0]


def test_a_digest_mismatch_writes_nothing(tmp_path: Path) -> None:
    tampered = {**DOCS, "invented-note": DOCS["invented-note"] + "extra"}
    with pytest.raises(LibError, match="does not match the pinned"):
        import_specs(tmp_path, cat=catalogue(), transport=transport(tampered))
    assert not (tmp_path / COMMIT / "invented-note.md").exists()
    assert not (tmp_path / COMMIT / "install.json").exists()


def test_a_pinned_file_that_is_not_text_is_refused_before_writing(tmp_path: Path) -> None:
    binary = {"evil": b"# T\n\n\xff\xfe\x00"}
    with pytest.raises(LibError, match="NUL|UTF-8"):
        import_specs(tmp_path, cat=catalogue(binary), transport=transport(binary))
    assert not (tmp_path / COMMIT / "evil.md").exists()


def test_an_oversize_body_is_refused() -> None:
    big = {"huge": b"x" * 5000}
    cat = catalogue(big)
    small = type(cat.specs[0])("huge", "huge.md", "huge", 10, cat.specs[0].sha256)  # a pin that says 10 bytes
    with pytest.raises(LibError, match="larger than"):
        Fetcher(HOSTS, transport(big)).get(cat.url(small), 100)


def test_only_https_from_named_hosts_is_fetched() -> None:
    for bad in (
        "http://raw.githubusercontent.com/x",
        "https://evil.invalid/x",
        "https://user:pw@raw.githubusercontent.com/x",
        "https://raw.githubusercontent.com:8443/x",
        "file:///etc/passwd",
    ):
        with pytest.raises(LibError, match="refusing"):
            check_url(bad, HOSTS)
    check_url(f"{BASE}{COMMIT}/x.md", HOSTS)
    with pytest.raises(LibError, match="refusing"):
        import_specs(Path("unused"), cat=catalogue(base="https://evil.invalid/"), transport=transport())


def test_importing_one_named_spec_and_an_unknown_name(tmp_path: Path) -> None:
    fetched: list[str] = []
    import_specs(tmp_path, ["invented-note"], cat=catalogue(), transport=transport(log=fetched))
    assert fetched == [f"{BASE}{COMMIT}/invented-note.md"]
    with pytest.raises(LibError) as raised:
        import_specs(tmp_path, ["nope"], cat=catalogue(), transport=transport())
    assert raised.value.hint == "known: invented-log, invented-note"


def test_pin_specs_reports_size_title_and_digest() -> None:
    pinned = pin_specs(BASE, COMMIT, ["invented-note"], Fetcher(HOSTS, transport(), min_interval=0))
    assert (pinned[0].title, pinned[0].size, pinned[0].sha256) == (
        "Signed Note",
        len(DOCS["invented-note"].encode()),
        sha(DOCS["invented-note"].encode()),
    )
    with pytest.raises(LibError, match="not a specification id"):
        pin_specs(BASE, COMMIT, ["../x"], Fetcher(HOSTS, transport()))


def test_the_packaged_catalogue_is_pinned_to_ctspys_commit() -> None:
    cat = packaged_catalogue()
    assert cat.commit == "09f3e519fe79bcbdccadcf821182e3b488a14d71"
    assert {"static-ct-api", "tlog-tiles", "tlog-checkpoint", "signed-note"} <= {s.id for s in cat.specs}
    assert cat.terms.licence == "CC-BY-4.0" and cat.terms.placement == "layer"
    assert all(len(s.sha256) == 64 for s in cat.specs)


# --- refs and tools --------------------------------------------------------------------------------------------


def test_refs_parse_with_prefix_commit_heading_text_and_paragraph() -> None:
    ref = library.parse_ref("c2sp:invented-log@0123456§Log Entries¶2")
    assert (ref.doc, ref.section, ref.para) == ("invented-log@0123456", "Log Entries", 2)
    assert library.parse_ref("invented-log").section is None
    assert library.parse_ref("invented-log::entry-format-details").section == "entry-format-details"
    for bad in ("", "invented-log:1-3", "invented-log#anchor", "§Log Entries", "c2sp:"):
        with pytest.raises(LibError):
            library.parse_ref(bad)


def test_read_a_section_a_block_and_a_page(home: Path) -> None:
    text = library.read("invented-log§Log Entries", home=home)
    assert text.startswith("First entry paragraph")
    assert "cite: C2SP, invented-log (The Invented Log), commit 0123456, §Log Entries." in text
    assert "unit: block" in text and "span: sha256:" in text
    assert "warning: 2 headings are titled 'Log Entries'" in text
    one = library.read("c2sp:invented-log@0123456§Log Entries¶2", home=home)
    assert one.startswith("Second entry paragraph, mentioning the origin line.\n")
    paged = library.read("invented-log§Log Entries", max_tokens=1, home=home)
    assert "next: start=2" in paged
    assert library.read("invented-log§Log Entries", start=2, max_tokens=1, home=home).startswith("Second entry")


def test_a_slug_names_a_heading_with_a_colon_and_duplicates_are_told_apart(home: Path) -> None:
    assert library.read("invented-log§entry-format-details", home=home).startswith("```")
    outline = library.outline("invented-log", home=home)
    for ref in (
        "§entry-format-details  ",
        "§another-section  ",
        "§log-entries  ",
        "§log-entries-1  ",
        "§Setext Heading  ",
    ):
        assert f"invented-log@0123456{ref}" in outline
    assert library.read("invented-log§log-entries-1", home=home).startswith("A second heading")


def test_a_whole_document_reads_from_the_top(home: Path) -> None:
    text = library.read("invented-note", home=home)
    assert text.startswith("# Signed Note\n\nA note is text followed by signatures.")
    assert "## Format" in text


def test_unknown_things_fail_with_a_remedy(home: Path, tmp_path: Path) -> None:
    with pytest.raises(LibError) as raised:
        library.read("invented-log§Log Entrys", home=home)
    assert "did you mean: Log Entries" in raised.value.hint
    with pytest.raises(LibError, match="span has"):
        library.read("invented-log§Log Entries¶99", home=home)
    with pytest.raises(LibError, match="static-ct-api is not imported") as missing:
        library.read("static-ct-api§X", home=home)
    assert missing.value.hint == "run: primarysource c2sp import"
    with pytest.raises(LibError, match="imported commits: 0123456"):
        library.read("invented-log@abcdef0§Log Entries", home=home)
    with pytest.raises(LibError, match="no C2SP specifications are imported") as empty:
        library.read("invented-log", home=tmp_path / "empty")
    assert empty.value.hint == "run: primarysource c2sp import"
    with pytest.raises(LibError, match="not a ref"):
        library.read("../evil§X", home=home)


def test_an_edited_install_is_detected(home: Path) -> None:
    path = home / COMMIT / "invented-note.md"
    path.write_bytes(path.read_bytes() + b"\nforged\n")
    with pytest.raises(LibError, match="does not match its recorded sha256"):
        library.read("invented-note§Format", home=home)


def test_outline_search_and_cite(home: Path) -> None:
    outline = library.outline("invented-note", home=home)
    assert "Signed Note  [invented-note@0123456]" in outline and "invented-note@0123456§Format  (1 blocks)" in outline
    hits = library.search("gasket code", home=home)
    assert hits.startswith("invented-log@0123456§log-entries¶1: First entry paragraph, mentioning the gasket")
    assert len(hits.strip().splitlines()) == 1 and "relaxed" not in hits  # not repeated under its parents
    relaxed = library.search("gasket nonexistentword", home=home)
    assert "relaxed: only some query words matched" in relaxed
    assert library.search("zzzzzz", home=home) == "no matches\n"
    only = library.search("signatures", doc="invented-note", home=home)
    assert only.startswith("invented-note@0123456§Signed Note¶1: A note is text followed by signatures.")
    cited = library.cite("invented-note§Format¶1", home=home)
    assert "cite: C2SP, invented-note (Signed Note), commit 0123456, §Format ¶1. CC BY 4.0." in cited
    assert f"span: sha256:{sha(b'The text ends with a newline.')[:16]}" in cited
    with pytest.raises(LibError, match="no searchable words"):
        library.search("!!!", home=home)


def test_search_pages_with_next(home: Path) -> None:
    first = library.search("the", limit=1, home=home)
    assert "next: start=2" in first
    assert library.search("the", limit=1, start=2, home=home).splitlines()[0] != first.splitlines()[0]


def test_docs_lists_the_packaged_catalogue_and_marks_imports(home: Path) -> None:
    listing = library.docs(home=home)
    assert listing.splitlines()[0].startswith("commit 09f3e51 (CC-BY-4.0, placement layer)")
    assert "not imported  static-ct-api" in listing


# --- the command and the server --------------------------------------------------------------------------------


@pytest.fixture
def registered(home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(home.parent))
    return home


def test_the_command_runs_through_the_core_cli(registered: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["c2sp", "read", "invented-note§Format¶1"]) == 0
    assert capsys.readouterr().out.startswith("The text ends with a newline.")
    assert cli.main(["c2sp", "outline", "invented-note"]) == 0
    assert cli.main(["c2sp", "search", "signatures"]) == 0
    assert cli.main(["c2sp", "cite", "invented-note§Format"]) == 0
    assert cli.main(["c2sp", "docs"]) == 0
    capsys.readouterr()
    assert cli.main(["c2sp", "read", "invented-note§Nope"]) == 1
    assert "hint:" in capsys.readouterr().err


def test_the_collection_object_declares_prefix_unit_and_grammar() -> None:
    assert (C2SP.name, C2SP.prefix) == ("c2sp", "c2sp_")
    assert C2SP.grammar.parse("static-ct-api@09f3e51§Log Entries¶3").doc == "static-ct-api@09f3e51"


def test_the_server_exposes_prefixed_tools_and_turns_errors_into_tool_errors(registered: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    server = registry.attribute(C2SP, C2SP.server, "server")
    names = [tool.name for tool in asyncio.run(server.list_tools())]
    assert names == ["c2sp_read", "c2sp_search", "c2sp_outline", "c2sp_cite", "c2sp_docs"]
    result = asyncio.run(server.call_tool("c2sp_read", {"ref": "invented-note§Format"}))
    assert "The text ends with a newline." in str(result)
    with pytest.raises(ToolError, match="hint: did you mean"):
        asyncio.run(server.call_tool("c2sp_read", {"ref": "invented-note§Formt"}))


def test_the_collection_grammar_is_the_real_parser() -> None:
    grammar = C2SP.grammar
    ref = grammar.parse("c2sp:static-ct-api@09f3e51§Log Entries¶2")
    assert grammar.parse(grammar.format(ref)) == ref
    with pytest.raises(LibError):
        grammar.parse("static-ct-api#x")
