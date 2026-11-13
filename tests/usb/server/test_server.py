"""The usb collection's wiring to the shared skeleton. The skeleton itself (loader, tools, server) is
tested once, in tests/test_pdfcorpus.py."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from primarysource.usb.server import mcp as server_mcp
from primarysource.usb.server.corpus import Corpus, load_corpus
from primarysource.usb.spec import SPEC

FIXTURES = Path(__file__).parents[2] / "pdfcorpus_fixtures" / "corpus"


def test_spec_names_this_collection() -> None:
    assert (SPEC.name, SPEC.server_name, SPEC.env_var) == ("usb", "usblib", "USBLIB_CORPUS")
    assert SPEC.fetch_command == "primarysource usb fetch"


def test_tool_surface() -> None:
    names = {t.name for t in asyncio.run(server_mcp.mcp.list_tools())}
    assert names == {"search", "read", "outline", "info", "cite"}


def test_server_reads_the_corpus_named_by_the_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mcp.server.mcpserver.exceptions import ToolError as McpToolError

    server_mcp.SERVER.reset()
    monkeypatch.setenv("USBLIB_CORPUS", str(tmp_path))
    with pytest.raises(McpToolError, match="primarysource usb fetch"):
        server_mcp.SERVER.info("synth-a")
    monkeypatch.setenv("USBLIB_CORPUS", str(FIXTURES))
    assert "number: SYNTH SP 000-1" in server_mcp.SERVER.info("synth-a")
    server_mcp.SERVER.reset()


def test_collection_corpus_carries_its_hint(tmp_path: Path) -> None:
    corpus = load_corpus(FIXTURES)
    assert corpus.fetch_hint == SPEC.fetch_hint
    assert isinstance(Corpus(tmp_path, ()), type(corpus))
