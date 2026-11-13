"""The command line and the MCP tools of a pkgdocs collection, over the synthesised demo collection."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pkgdocs_fixture import COMMIT, FILES, INCLUDE, URL, installed_library, make_spec, make_tar, manifest_for

from primarysource import registry
from primarysource.debpolicy import COLLECTION as DEBPOLICY
from primarysource.gitdocs import COLLECTION as GITDOCS
from primarysource.kconfig import COLLECTION as KCONFIG
from primarysource.pep import COLLECTION as PEP
from primarysource.pkgdocs.runtime import Library, make_collection
from primarysource.pkgdocs.serving import build_server, run
from primarysource.pms import COLLECTION as PMS
from primarysource.rpmdocs import COLLECTION as RPMDOCS

COLLECTIONS = [GITDOCS, DEBPOLICY, RPMDOCS, PMS, PEP, KCONFIG]


@pytest.mark.parametrize("collection", COLLECTIONS, ids=lambda c: c.name)
def test_each_collection_is_a_registry_entry_with_a_prefix_a_server_and_a_command(
    collection: registry.Collection,
) -> None:
    assert collection.prefix == f"{collection.name}_"
    assert collection.server == f"primarysource.{collection.name}.server:server"
    assert collection.cli == f"primarysource.{collection.name}.cli:main"
    entry = registry.attribute(collection, collection.cli, "command line")
    assert callable(entry)


@pytest.mark.parametrize("collection", COLLECTIONS, ids=lambda c: c.name)
def test_each_collection_serves_prefixed_tools(collection: registry.Collection) -> None:
    pytest.importorskip("mcp")
    server = registry.attribute(collection, collection.server, "server")
    names = [tool.name for tool in asyncio.run(server.list_tools())]
    assert names == [collection.prefix + n for n in ("read", "outline", "search", "cite", "docs", "status")]


def test_a_collection_is_registered_by_a_registry_entry_built_from_its_spec() -> None:
    entry = make_collection(make_spec(None), "primarysource.demo")
    assert (entry.name, entry.prefix, entry.server) == ("demo", "demo_", "primarysource.demo.server:server")
    assert entry.grammar.parse("alpha@aaaa§1.1¶2").section == "1.1"


def test_the_tools_answer_in_text_and_a_failure_is_a_tool_error_naming_the_remedy(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    library = installed_library(tmp_path)
    server = build_server(library.spec, library)
    result = asyncio.run(server.call_tool("demo_read", {"ref": "alpha§1.1¶1"}))
    assert "Text about gaskets and sprockets." in str(result)
    assert "gaskets" in str(asyncio.run(server.call_tool("demo_search", {"query": "gaskets"})))
    assert "alpha  Alpha" in str(asyncio.run(server.call_tool("demo_docs", {})))
    with pytest.raises(ToolError, match="hint: did you mean"):
        asyncio.run(server.call_tool("demo_read", {"ref": "alfa§1"}))
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert "Examples: demo:alpha§First part" in (tools["demo_read"].description or "")
    assert tools["demo_read"].annotations is not None and tools["demo_read"].annotations.read_only_hint


def test_the_command_imports_reads_outlines_searches_and_cites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = manifest_for(FILES, INCLUDE)
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(make_tar(FILES))
    library = Library(make_spec(digest), tmp_path / "home")
    assert run(library.spec, ["import", "--tree", "main", "--archive", str(archive)], library) == 0
    out = capsys.readouterr().out
    assert f"main v1 {COMMIT[:12]}: 2 documents" in out and "matches the pin" in out
    assert run(library.spec, ["read", "alpha§1.1¶1"], library) == 0
    assert capsys.readouterr().out.startswith("Text about gaskets and sprockets.\n\ncite: ")
    assert run(library.spec, ["outline", "alpha"], library) == 0
    assert "1.2.1  Notes" in capsys.readouterr().out
    assert run(library.spec, ["search", "sprockets", "--limit", "1"], library) == 0
    assert "[sprockets]" in capsys.readouterr().out
    assert run(library.spec, ["cite", "alpha§1.1"], library) == 0
    assert "licence CC0-1.0" in capsys.readouterr().out
    assert run(library.spec, ["docs", "al"], library) == 0
    assert capsys.readouterr().out.startswith("alpha  Alpha")
    assert run(library.spec, ["status"], library) == 0
    assert "imported" in capsys.readouterr().out


def test_a_failing_command_exits_1_with_the_error_and_its_hint_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = Library(make_spec(None), tmp_path / "empty")
    assert run(library.spec, ["read", "alpha§1"], library) == 1
    err = capsys.readouterr().err
    assert "error: Demo documents is not imported" in err and "hint: primarysource demo import" in err
    pinned = Library(make_spec(manifest_for(FILES, INCLUDE)), tmp_path / "empty")
    assert run(pinned.spec, ["import", "--archive", str(tmp_path / "gone.tar.gz"), "--tree", "main"], pinned) == 1
    assert "no file at" in capsys.readouterr().err
    assert URL.startswith("https://")


def test_the_command_prints_utf8_whatever_the_console_code_page_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = installed_library(tmp_path)
    assert run(library.spec, ["read", "alpha§1.1¶1"], library) == 0
    assert "§1.1¶1" in capsys.readouterr().out


BUILTIN_LINES = {
    "gitdocs": "primarysource.gitdocs:COLLECTION",
    "debpolicy": "primarysource.debpolicy:COLLECTION",
    "rpmdocs": "primarysource.rpmdocs:COLLECTION",
    "pms": "primarysource.pms:COLLECTION",
    "pep": "primarysource.pep:COLLECTION",
    "kconfig": "primarysource.kconfig:COLLECTION",
}


def test_the_proposed_builtin_lines_register_all_six_in_the_core_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from primarysource import cli

    for name, target in BUILTIN_LINES.items():
        monkeypatch.setitem(registry.BUILTIN, name, target)
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    assert cli.main(["collections"]) == 0
    listed = capsys.readouterr().out.split()
    assert set(BUILTIN_LINES) <= set(listed)
    for name in BUILTIN_LINES:
        loaded = registry.load(name)
        assert loaded.name == name and loaded.prefix == f"{name}_"
    assert cli.main(["pep", "status"]) == 0
    assert "Python Enhancement Proposals" in capsys.readouterr().out
    assert cli.main(["debpolicy", "read", "5.6.1"]) == 1
    assert "hint: primarysource debpolicy import" in capsys.readouterr().err
