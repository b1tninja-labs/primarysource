from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from primarysource.cve import cli

from .conftest import KERNEL_BACKPORT_ID, WEB_ID

TOOLS = {"cve_info", "cve_search", "cve_read", "cve_kev", "cve_kernel", "cve_kernel_list"}


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_reports_missing_corpus_with_exit_2(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = run(capsys, "search", "anything")
    assert code == 2
    lines = err.splitlines()
    assert lines[0].startswith("error: no cve index at ")
    assert lines[-1] == "action: primarysource cve sync"


def test_cli_prints_the_same_text_the_tools_return(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = run(capsys, "kernel", KERNEL_BACKPORT_ID, "6.18.62")
    assert code == 0
    assert out.splitlines()[0] == f"{KERNEL_BACKPORT_ID} on kernel 6.18.62: not_affected  (confidence: high)"
    code, out, _err = run(capsys, "read", WEB_ID)
    assert code == 0 and out.splitlines()[0] == f"{WEB_ID}  PUBLISHED" and f"cite: {WEB_ID} [" in out
    code, out, _err = run(capsys, "search", "Widget")
    assert code == 0 and WEB_ID in out


def test_json_flag_prints_the_services_dict(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = run(capsys, "--json", "kernel", KERNEL_BACKPORT_ID, "6.18.62")
    assert code == 0 and json.loads(out)["verdict"] == "not_affected"
    code, out, _err = run(capsys, "--json", "read", WEB_ID)
    assert code == 0 and json.loads(out)["ref"] == WEB_ID
    code, out, _err = run(capsys, "--json", "search", "Widget")
    assert code == 0 and json.loads(out)["hits"][0]["ref"] == WEB_ID


def test_path_names_the_home_and_the_index(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = run(capsys, "path")
    assert code == 0 and f"home: {home}" in out and f"index: {home / 'index.sqlite'}" in out


def test_gitignore_covers_the_corpus() -> None:
    text = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.sqlite", "*.zip", "*.csv.gz"):
        assert pattern in text


def test_mcp_tools_end_to_end(synced: Path) -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "primarysource.cve", "mcp"],
            env={**os.environ, "CVELIB_HOME": str(synced)},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == TOOLS
            result = await session.call_tool("cve_kernel", {"ref": KERNEL_BACKPORT_ID, "version": "6.18.62"})
            assert result.structured_content is None
            text = result.content[0].text
            assert text.startswith(f"{KERNEL_BACKPORT_ID} on kernel 6.18.62: not_affected")
            assert "cite: kernel CNA" in text
            result = await session.call_tool("cve_kev", {"ref": WEB_ID})
            assert "listed in CISA KEV" in result.content[0].text

    anyio.run(scenario)


def test_mcp_returns_an_error_with_the_action_without_corpus(home: Path) -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "primarysource.cve", "mcp"],
            env={**os.environ, "CVELIB_HOME": str(home)},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("cve_search", {"query": "x"})
            assert result.is_error is True
            assert result.content[0].text.splitlines()[-1] == "action: primarysource cve sync"

    anyio.run(scenario)


def test_the_core_command_hands_the_line_to_the_cve_collection(
    synced: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from primarysource import cli as core

    assert core.main(["cve", "kernel", KERNEL_BACKPORT_ID, "6.18.62"]) == 0
    assert "not_affected" in capsys.readouterr().out.splitlines()[0]
    assert core.main(["collections"]) == 0
    assert "cve" in capsys.readouterr().out.split()
    assert core.main(["cve", "read", "CVE-2099-99999"]) == 2
    assert capsys.readouterr().err.startswith("error: CVE-2099-99999 is in none of the synced sources")
