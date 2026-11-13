from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from zimfixture import build_zim  # noqa: E402

from primarysource.zim import cli, mcp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOOLS = {
    "zim_libraries",
    "zim_resolve",
    "zim_search",
    "zim_read",
    "zim_outline",
    "zim_links",
    "zim_cite",
    "zim_available",
}


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_list_search_read_cite(acme: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "list")
    assert code == 0 and "acme_en_widgets  Acme Widgets Docs  [full-text" in out and "2026-10-01" in out
    code, out, _ = run(capsys, "search", "timeout flange", "-l", "acme")
    assert code == 0 and "acme_en_widgets§guide/config" in out
    code, out, _ = run(capsys, "read", "acme§guide/config#timeouts")
    assert "## Timeouts" in out and "-- Acme Widgets Docs [acme_en_widgets]" in out
    code, out, _ = run(capsys, "read", "acme§guide/config", "--max-tokens", "40")
    assert "-- next: zimlore read 'acme_en_widgets§guide/config' --start " in out
    code, out, _ = run(capsys, "cite", "acme::guide/config#timeouts", "--json")
    assert json.loads(out)["cite"].endswith("entry guide/config#timeouts")


def test_cli_errors_exit_2_and_name_the_fix(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = run(capsys, "list")
    assert code == 2 and "no ZIM files found" in err and "fix: download one: zimlore catalog" in err
    code, out, _ = run(capsys, "read", "x§y", "--json")
    assert code == 2 and json.loads(out)["error"].startswith("no ZIM files found")


def test_cli_info_works_without_any_zim_and_reports_the_binding(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "info", "--json")
    data = json.loads(out)
    assert code == 0 and data["installed"] == 0 and data["libzim"] is True
    assert data["home"] == str(home)


def _text(result: object) -> str:
    return str(result.content[0].text)  # type: ignore[attr-defined]


def _payload(result: object) -> dict[str, object]:
    loaded = json.loads(result.content[0].text)  # type: ignore[attr-defined]
    assert isinstance(loaded, dict)
    return loaded


def test_mcp_stdio_handshake_lists_the_tools_and_serves_a_library(tmp_path: Path) -> None:
    """Drives the real server over stdio. Catches stdout pollution, which importing the module never would."""
    empty = tmp_path / "empty"
    (empty / "zim").mkdir(parents=True)
    full = tmp_path / "full"
    build_zim(full / "zim")

    async def drive(home: Path) -> tuple[set[str], dict[str, object], dict[str, object], dict[str, object]]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "primarysource.zim.mcp"],
            env={**os.environ, "ZIMLORE_HOME": str(home)},
            cwd=ROOT,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            libs = await session.call_tool("zim_libraries", {})
            search = await session.call_tool("zim_search", {"query": "timeout flange spin", "library": "acme"})
            page = await session.call_tool("zim_read", {"ref": "acme§guide/config#timeouts"})
            return names, _payload(libs), _payload(search), _payload(page)

    names, libs, search, _ = anyio.run(drive, empty)
    assert names == TOOLS
    assert "error" in libs and "zimlore get" in str(libs["user_command"]), (
        "no library is an error object, never an empty list"
    )
    assert "zim_available" in str(libs["hint"]) and "zimlore" not in str(libs["hint"]), "the hint names tools"
    assert "error" in search and "hits" not in search

    names, libs, search, page = anyio.run(drive, full)
    assert [row["name"] for row in libs["libraries"]] == ["acme_en_widgets"]  # type: ignore[attr-defined]
    assert search["hits"][0]["ref"] == "acme_en_widgets§guide/config"  # type: ignore[index]
    assert str(page["content"]).startswith("## Timeouts")


def test_mcp_tool_errors_are_objects_not_crashes(acme: Path) -> None:
    app = mcp.build()
    result = anyio.run(app.call_tool, "zim_read", {"ref": "acme§nope/nope"})  # type: ignore[attr-defined]
    payload = json.loads(result.content[0].text)
    assert "has no entry" in payload["error"] and payload["hint"]


def test_mcp_without_the_extra_exits_2_with_the_install_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    assert cli.main(["mcp"]) == 2
    assert "zimlore[mcp]" in capsys.readouterr().err


def test_a_platform_without_libzim_still_gets_info_and_a_clear_error(
    acme: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Windows on ARM has no libzim wheel: the CLI must say so and keep working, not crash on import."""
    from primarysource.zim import library

    library.close_all()
    for module in ("libzim", "libzim.reader", "libzim.search", "libzim.suggestion", "libzim.writer"):
        monkeypatch.setitem(sys.modules, module, None)
    code, out, _ = run(capsys, "info", "--json")
    data = json.loads(out)
    assert code == 0 and data["libzim"] is False
    assert data["installed"] == 0 and "libzim" in data["problems"][0]["error"]
    code, _, err = run(capsys, "search", "x")
    assert code == 2 and "no ZIM files found" in err
    assert "could not be read" in err, "unreadable files are reported, and nothing pretends to search"


def test_an_unexpected_failure_names_the_type_but_not_the_path_and_writes_nothing_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom() -> None:
        raise OSError("cannot open /home/someone/private/secret.zim")

    payload = json.loads(mcp._run(boom))
    assert payload["error"].startswith("OSError") and "secret" not in payload["error"]
    captured = capsys.readouterr()
    assert captured.out == "", "stdout is the protocol"
    assert "secret.zim" in captured.err, "the detail is kept for the operator"


def test_the_server_instructions_and_the_plan_call_zim_text_untrusted() -> None:
    assert "untrusted data" in mcp.INSTRUCTIONS and "never instructions" in mcp.INSTRUCTIONS
    assert "untrusted data" in (ROOT / "docs" / "zim" / "PLAN.md").read_text(encoding="utf-8")


def test_mcp_answers_are_compact_json_and_the_list_tools_take_a_budget(tmp_path: Path) -> None:
    """Over the real stdio server: no indentation (tokens), `§` kept as a character, and the new parameters exist."""
    home = tmp_path / "h"
    build_zim(home / "zim")

    async def drive() -> tuple[dict[str, set[str]], str, dict[str, object]]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "primarysource.zim.mcp"],
            env={**os.environ, "ZIMLORE_HOME": str(home)},
            cwd=ROOT,
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            schemas = {t.name: set(t.input_schema["properties"]) for t in (await session.list_tools()).tools}
            raw = await session.call_tool("zim_search", {"query": "timeout flange spin", "library": "acme"})
            outline = await session.call_tool("zim_outline", {"ref": "acme§guide/config", "max_tokens": 40})
            return schemas, _text(raw), _payload(outline)

    schemas, text, outline = anyio.run(drive)
    assert {"limit", "verbose"} <= schemas["zim_libraries"] and "max_tokens" in schemas["zim_outline"]
    assert "\n" not in text and ": " not in text.split('"excerpt"')[0], "compact separators, no indentation"
    assert "acme_en_widgets§guide/config" in text, "the section sign is written as a character, not a unicode escape"
    assert outline["truncated"] is True and "next" in outline
