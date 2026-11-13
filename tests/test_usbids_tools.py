"""The usbids readers, command and MCP server over the invented file, plus the core's wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from cursor_check import follow_list, follow_read
from usbids_fixture import DIGEST, install

from primarysource import cli, registry
from primarysource.errors import LibError
from primarysource.usbids import COLLECTION, store, tools


@pytest.fixture
def base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)
    return install(tmp_path)


def test_a_device_shows_its_vendor_and_cites_the_snapshot(base: Path) -> None:
    out = tools.lookup("usbids:0001:0002")
    assert out.startswith("usbids:0001:0002  Frobnicator 2000  [device]\nwithin: usbids:0001  Gizmo Works  [vendor]")
    assert "cite: USB ID Database usb.ids 2099.01.02 (2099-01-02 03:04:05), usbids:0001:0002" in out
    assert "unit: line" in out


def test_a_vendor_lists_its_devices_and_a_device_its_interfaces(base: Path) -> None:
    out = tools.lookup("0001")
    assert "  usbids:0001:0002  Frobnicator 2000\n  usbids:0001:0003  Frobnicator Mini" in out
    assert "  usbids:0001:0003:01  Control interface" in tools.lookup("usbids:0001:0003")


def test_a_long_vendor_pages_and_the_footer_says_where_to_resume(base: Path) -> None:
    first = tools.lookup("usbids:0001", max_tokens=1)
    assert "span: 1-1 of 3" in first and "next: usbids:0001¶2" in first
    second = tools.lookup("usbids:0001¶2", max_tokens=1)
    assert second.startswith("within:") is False and "span: 2-2 of 3" in second
    last = tools.lookup("usbids:0001¶3", max_tokens=1000)
    assert "next:" not in last
    with pytest.raises(LibError, match="span has 3 lines"):
        tools.lookup("usbids:0001¶4")
    whole = tools.lookup("usbids:0001").split("\n\n")[0]
    bodies, refs = follow_read(lambda ref: tools.lookup(ref, max_tokens=1), "0001")
    assert refs == ["0001", "usbids:0001¶2", "usbids:0001¶3"] and "\n".join(bodies) == whole


def test_other_sections_resolve(base: Path) -> None:
    assert "usbids:hut/01/006  Keyboard  [usage]\nwithin: usbids:hut/01  Generic Desktop Controls" in tools.lookup(
        "usbids:hut/01/006"
    )
    assert tools.lookup("usbids:lang/0409/01").startswith("usbids:lang/0409/01  US  [dialect]")
    assert tools.lookup("usbids:hcc/09").startswith("usbids:hcc/09  German  [country code]")


def test_a_missing_entry_is_an_error_that_says_what_is_there_not_an_empty_result(base: Path) -> None:
    with pytest.raises(LibError, match="usbids:0001:9999 is not listed; its vendor is 'Gizmo Works'") as caught:
        tools.lookup("usbids:0001:9999")
    assert "usbids_lookup('usbids:0001')" in caught.value.hint
    with pytest.raises(LibError, match="not in usb.ids 2099.01.02") as caught:
        tools.lookup("usbids:ffff")
    assert "usbids_search" in caught.value.hint
    with pytest.raises(LibError, match="not a usbids ref"):
        tools.lookup("../../etc/passwd")


def test_search_ranks_whole_words_first_and_counts_a_vendor_name_for_its_devices(base: Path) -> None:
    out = tools.search("frobnicator")
    lines = out.splitlines()
    assert lines[0] == "usbids:0001:0002  Gizmo Works / Frobnicator 2000"
    assert "usbids:0a0a:0001  Sprocket Ltd. / Frobnicator 2000 clone" in lines
    assert "span: 1-3 of 3" in out
    assert tools.search("sprocket clone").splitlines()[0].startswith("usbids:0a0a:0001")
    assert tools.search("keyboard", section="hut").splitlines()[0] == "usbids:hut/01/006  Keyboard"
    assert "usbids:hut/07  Keyboard/Keypad" in tools.search("keypad")


def test_search_pages_and_an_empty_result_means_nothing_matched(base: Path) -> None:
    first = tools.search("frobnicator", limit=1)
    assert "next: start=1" in first
    assert "span: 3-3 of 3" in tools.search("frobnicator", limit=1, start=2)
    every = tools.search("frobnicator").split("\n\n")[0].split("\n")
    assert follow_list(lambda start: tools.search("frobnicator", limit=1, start=start)) == every
    none = tools.search("zzyzx")
    assert none.startswith("no entry matches 'zzyzx'") and "span:" not in none


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"text": "!!!"}, "no letters or digits"),
        ({"text": "x" * 201}, "over 200"),
        ({"text": "a", "section": "nope"}, "unknown section"),
        ({"text": "a", "limit": 0}, "limit must be"),
        ({"text": "a", "limit": 201}, "limit must be"),
        ({"text": "a", "start": -1}, "limit must be"),
    ],
)
def test_search_refuses_hostile_arguments(base: Path, kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(LibError, match=message):
        tools.search(**kwargs)  # type: ignore[arg-type]


def test_a_query_with_regex_or_sql_characters_is_just_words(base: Path) -> None:
    assert tools.search(".* OR 1=1; --").startswith("no entry matches")
    assert "Frobnicator Mini" in tools.search("frobnicator (mini)[")


def test_classify_names_the_triple_in_either_spelling(base: Path) -> None:
    out = tools.classify("0x09", "00", "2")
    assert out.splitlines()[:3] == [
        "usbids:class/09  Hub  [class]",
        "usbids:class/09/00  Unused  [subclass]",
        "usbids:class/09/00/02  TT per port  [protocol]",
    ]
    assert "(not listed in usb.ids)" in tools.classify("09", "7f")
    assert tools.classify("FF").startswith("usbids:class/ff  Vendor Specific Class")
    with pytest.raises(LibError, match="class 42 is not in usb.ids"):
        tools.classify("42")
    with pytest.raises(LibError, match="not one or two hex digits"):
        tools.classify("zz")
    with pytest.raises(LibError, match="needs a subclass"):
        tools.classify("09", None, "00")


def test_sections_reports_the_snapshot_digest_licence_and_counts(base: Path) -> None:
    out = tools.sections()
    assert f"sha256 {DIGEST}  (pinned snapshot)" in out
    assert (
        "licence GPL-2.0-or-later OR BSD-3-Clause" in out
        and "  vendor: 7" in out
        and "unparsed lines at import: 0" in out
    )


def test_not_imported_is_an_error_naming_the_import_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    with pytest.raises(LibError, match="not imported") as caught:
        tools.lookup("usbids:0001")
    assert caught.value.action == "primarysource usbids import" and caught.value.hint == ""


def test_a_file_changed_after_import_is_refused_not_served(base: Path) -> None:
    (base / "usb.ids").write_bytes((base / "usb.ids").read_bytes() + b"0c0c  Added by hand\n")
    with pytest.raises(LibError, match="changed after import") as caught:
        store.load(base)
    assert "--force" in caught.value.action


def test_the_library_lives_under_primarysource_home(base: Path, tmp_path: Path) -> None:
    assert store.home() == tmp_path / "usbids"


def test_a_garbled_manifest_is_an_error_not_a_crash(base: Path) -> None:
    (base / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(LibError, match="not a readable manifest"):
        store.load(base)


def test_the_collection_loads_through_the_registry() -> None:
    assert "usbids" in registry.available()
    loaded = registry.load("usbids")
    assert loaded is COLLECTION and loaded.prefix == "usbids_" and loaded.name == "usbids"


def test_the_core_command_dispatches_to_the_collection(base: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["usbids", "lookup", "usbids:0a0a:0001"]) == 0
    assert capsys.readouterr().out.startswith("usbids:0a0a:0001  Frobnicator 2000 clone  [device]")
    assert cli.main(["usbids", "search", "mini"]) == 0
    assert "usbids:0001:0003  Gizmo Works / Frobnicator Mini" in capsys.readouterr().out
    assert cli.main(["usbids", "classify", "09", "00"]) == 0
    assert "usbids:class/09/00  Unused" in capsys.readouterr().out
    assert cli.main(["usbids", "sections"]) == 0
    assert "usb.ids 2099.01.02" in capsys.readouterr().out


def test_the_command_reports_an_error_with_its_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    assert cli.main(["usbids", "lookup", "usbids:0001"]) == 1
    err = capsys.readouterr().err
    assert "error: usb.ids is not imported" in err and "action: primarysource usbids import" in err


def test_the_server_offers_the_four_prefixed_tools() -> None:
    pytest.importorskip("mcp")
    server = registry.attribute(COLLECTION, COLLECTION.server, "server")
    names = [tool.name for tool in asyncio.run(server.list_tools())]
    assert names == ["usbids_lookup", "usbids_search", "usbids_classify", "usbids_sections"]
    assert all(name.startswith(COLLECTION.prefix) for name in names)


def test_a_tool_answers_text_and_a_failure_is_a_tool_error_naming_the_remedy(base: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from primarysource.usbids.server import server

    result = asyncio.run(server.call_tool("usbids_lookup", {"ref": "usbids:class/09/00"}))
    assert "TT per port" in str(result)
    with pytest.raises(ToolError, match="hint: usbids_lookup"):
        asyncio.run(server.call_tool("usbids_lookup", {"ref": "usbids:0001:9999"}))
    with pytest.raises(ToolError, match="hint: expected usbids"):
        asyncio.run(server.call_tool("usbids_lookup", {"ref": "$(rm -rf /)"}))
