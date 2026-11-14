"""posix and ieee802 behind the core's `primarysource` command and MCP server, over invented pages."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from ieee_posixfixture import archive

from primarysource import cli, registry
from primarysource.ieee import IEEE802, POSIX
from primarysource.ieee.importer import import_posix


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path, pinned = archive(tmp_path)
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path / "home"))
    import_posix(path, home=tmp_path / "home", pinned=pinned)
    return tmp_path / "home"


def test_the_command_reads_outlines_and_greps(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["posix", "outline", "functions/frob"]) == 0
    assert "DESCRIPTION  posix-2024§functions/frob#tag_99_01_02" in capsys.readouterr().out
    assert cli.main(["posix", "read", "posix-2024§functions/frob#tag_99_01_02¶2"]) == 0
    assert capsys.readouterr().out.startswith("A second paragraph about gaskets.")
    assert cli.main(["posix", "grep", "flanges"]) == 0
    assert "#tag_99_01_02_01¶1: Sub-section text about flanges." in capsys.readouterr().out
    assert cli.main(["posix", "info", "frob"]) == 0
    assert capsys.readouterr().out.startswith("posix-2024§functions/frob  XSH frob")
    assert cli.main(["posix", "pages", "utilities"]) == 0
    assert capsys.readouterr().out.split() == ["utilities/["]


def test_the_command_reports_an_error_with_its_remedy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    assert cli.main(["ieee802", "outline", "802.3-2022"]) == 1
    assert cli.main(["posix", "read", "posix-2024§functions/open"]) == 1


def test_each_collection_serves_prefixed_tools(home: Path) -> None:
    pytest.importorskip("mcp")
    posix_server = registry.attribute(POSIX, POSIX.server, "server")
    names = [tool.name for tool in asyncio.run(posix_server.list_tools())]
    assert names == ["posix_read", "posix_outline", "posix_grep", "posix_pages", "posix_info"]
    ieee802_server = registry.attribute(IEEE802, IEEE802.server, "server")
    assert [tool.name for tool in asyncio.run(ieee802_server.list_tools())] == ["ieee802_outline"]


def test_a_tool_answers_text_and_a_failure_is_a_tool_error_naming_the_remedy(home: Path) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from primarysource.ieee.server import posix_server

    result = asyncio.run(posix_server.call_tool("posix_read", {"ref": "functions/frob#tag_99_01_03"}))
    assert "Upon success, zero sprockets." in str(result)
    with pytest.raises(ToolError, match="hint: did you mean"):
        asyncio.run(posix_server.call_tool("posix_outline", {"page": "functions/frab"}))
