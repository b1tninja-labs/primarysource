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
    assert "primarysource cve sync" in err


def test_cli_kernel_and_read(synced: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = run(capsys, "kernel", KERNEL_BACKPORT_ID, "6.18.62")
    assert code == 0
    assert json.loads(out)["verdict"] == "not_affected"
    code, out, _err = run(capsys, "read", WEB_ID)
    assert code == 0 and json.loads(out)["ref"] == WEB_ID
    code, out, _err = run(capsys, "search", "Widget")
    assert code == 0 and WEB_ID in out


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
            answer = json.loads(result.content[0].text)
            assert answer["verdict"] == "not_affected"
            assert answer["source"].startswith("kernel CNA")
            result = await session.call_tool("cve_kev", {"ref": WEB_ID})
            assert json.loads(result.content[0].text)["status"] == "listed"

    anyio.run(scenario)


def test_mcp_returns_error_object_without_corpus(home: Path) -> None:
    async def scenario() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "primarysource.cve", "mcp"],
            env={**os.environ, "CVELIB_HOME": str(home)},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("cve_search", {"query": "x"})
            answer = json.loads(result.content[0].text)
            assert "primarysource cve sync" in answer["hint"]

    anyio.run(scenario)
