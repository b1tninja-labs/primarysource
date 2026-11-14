"""The nist collection's wiring to the shared skeleton. The skeleton itself (loader, tools, server) is
tested once, in tests/test_pdfcorpus.py."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from primarysource.nist.server import mcp as server_mcp
from primarysource.nist.collection import main
from primarysource.nist.server.corpus import Corpus, CorpusError, load_corpus
from primarysource.nist.spec import SPEC

FIXTURES = Path(__file__).parents[2] / "pdfcorpus_fixtures" / "corpus"


def test_spec_names_this_collection() -> None:
    assert (SPEC.name, SPEC.server_name, SPEC.env_var) == ("nist", "nistlib", "NISTLIB_CORPUS")
    assert SPEC.fetch_command == "primarysource nist fetch"
    assert SPEC.index_command == "primarysource nist index"


def test_tool_surface() -> None:
    names = {t.name for t in asyncio.run(server_mcp.mcp.list_tools())}
    assert names == {"search", "read", "outline", "info", "cite"}


def test_server_reads_the_corpus_named_by_the_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server_mcp.SERVER.reset()
    monkeypatch.setenv("NISTLIB_CORPUS", str(tmp_path))
    with pytest.raises(CorpusError) as ei:
        server_mcp.SERVER.info("synth-a")
    assert ei.value.action == "primarysource nist fetch"
    monkeypatch.setenv("NISTLIB_CORPUS", str(FIXTURES))
    assert "number: SYNTH SP 000-1" in server_mcp.SERVER.info("synth-a")
    server_mcp.SERVER.reset()


def test_collection_corpus_carries_its_commands(tmp_path: Path) -> None:
    corpus = load_corpus(FIXTURES)
    assert (corpus.fetch_command, corpus.index_command) == (SPEC.fetch_command, SPEC.index_command)
    assert corpus.tool("read") == "nist_read"
    bare = Corpus(tmp_path, ())
    assert isinstance(bare, type(corpus)) and bare.index_command == SPEC.index_command


def test_the_collection_cli_builds_the_search_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURES, corpus)
    monkeypatch.setenv("NISTLIB_CORPUS", str(corpus))
    server_mcp.SERVER.reset()
    with pytest.raises(CorpusError) as ei:
        server_mcp.SERVER.search("quokka")
    assert ei.value.action == "primarysource nist index"
    assert main(["index"]) == 0
    assert "synth-a§2.1" in server_mcp.SERVER.search("quokka")
    server_mcp.SERVER.reset()


def test_the_collection_cli_writes_the_defaults_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURES, corpus)
    monkeypatch.setenv("NISTLIB_CORPUS", str(corpus))
    assert main(["status"]) == 0
    written = json.loads((corpus / "defaults.json").read_text(encoding="utf-8"))
    assert written["schema"] == 1 and written["defaults"] == {}
    assert main([]) == 2 and "status" in capsys.readouterr().out
