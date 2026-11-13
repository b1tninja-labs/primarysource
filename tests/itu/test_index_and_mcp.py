"""The index on the core's `primarysource/index.py`, its staleness gate and the MCP stdio surface, on invented text.

Nothing here is ITU text: the "pages" are sentences made up for the test, and the "PDF" is a few arbitrary
bytes because the index only hashes the file. That is what lets these run without the corpus, which
`test_license.py` requires of every test.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
from pathlib import Path

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from primarysource import index as core
from primarysource.errors import LibError
from primarysource.itu import corpus, index, text
from primarysource.itu.sources import Edition

SYNTHETIC = Edition(
    key="T.0#0000-00",
    rec="T.0",
    edition="00/0000",
    title="Synthetic",
    status="test",
    artifact="none",
    sha256="",
    octets=0,
)

PAGES = [
    "1.1 Widgets are counted in whole units and never in fractions of a unit.\n"
    "1.2 Gadgets are ordered by colour before they are ordered by size at all.\n"
]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ITULIB_HOME", str(tmp_path))
    monkeypatch.setattr(text, "pages", lambda _path: PAGES)
    pdf = corpus.pdf_path(SYNTHETIC)
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"first edition")
    return tmp_path


def test_index_serves_clauses_it_was_built_from(home: Path) -> None:
    assert index.build(SYNTHETIC) == 2
    clause = index.read(SYNTHETIC, "1.2")
    assert clause is not None
    assert "colour" in clause.body
    assert [hit.number for hit in index.search(SYNTHETIC, "widgets").hits] == ["1.1"]


def test_the_index_is_the_core_schema_with_the_clause_number_heading_and_body_columns(home: Path) -> None:
    index.build(SYNTHETIC)
    with sqlite3.connect(index._db_path(SYNTHETIC)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == core.SCHEMA_VERSION
        rows = connection.execute("SELECT doc_title, section_id, title FROM sections ORDER BY id").fetchall()
    assert rows == [("1.1", "1.1", ""), ("1.2", "1.2", "")], "number in doc_title; no heading of their own here"


def test_index_refuses_to_serve_after_the_corpus_changes(home: Path) -> None:
    index.build(SYNTHETIC)
    corpus.pdf_path(SYNTHETIC).write_bytes(b"republished edition")
    with pytest.raises(LibError, match="changed since the index was built") as stale:
        index.search(SYNTHETIC, "widgets")
    assert stale.value.action == "primarysource itu index T.0#0000-00"
    with pytest.raises(LibError, match="changed since the index was built"):
        index.read(SYNTHETIC, "1.1")
    index.build(SYNTHETIC)
    assert index.read(SYNTHETIC, "1.1") is not None


def test_the_pdf_is_hashed_only_when_its_size_or_mtime_changes(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index.build(SYNTHETIC)
    hashed: list[Path] = []
    real = index._sha256

    def counting(path: Path) -> str:
        hashed.append(path)
        return real(path)

    monkeypatch.setattr(index, "_sha256", counting)
    index.search(SYNTHETIC, "widgets")
    index.read(SYNTHETIC, "1.1")
    assert hashed == [], "size and mtime match the recorded ones: no hash on open"
    pdf = corpus.pdf_path(SYNTHETIC)
    later = pdf.stat().st_mtime_ns + 5_000_000_000
    os.utime(pdf, ns=(later, later))
    index.read(SYNTHETIC, "1.1")
    assert len(hashed) == 1, "a touched file is hashed once, and the same bytes still serve"
    index.read(SYNTHETIC, "1.2")
    assert len(hashed) == 1, "and the match is remembered, not hashed again on every call"


def test_a_read_only_index_file_serves(home: Path) -> None:
    index.build(SYNTHETIC)
    db = index._db_path(SYNTHETIC)
    db.chmod(stat.S_IREAD)
    try:
        assert [hit.number for hit in index.search(SYNTHETIC, "gadgets").hits] == ["1.2"]
        assert not Path(f"{db}-wal").exists(), "serving opens ?mode=ro and creates nothing beside the index"
    finally:
        db.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_failed_rebuild_leaves_the_old_index_serving(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index.build(SYNTHETIC)
    monkeypatch.setattr(text, "pages", lambda _path: ["no numbered headings here"])
    with pytest.raises(LibError, match="0 clauses"):
        index.build(SYNTHETIC)
    assert [hit.number for hit in index.search(SYNTHETIC, "widgets").hits] == ["1.1"]
    assert [p.name for p in index._db_path(SYNTHETIC).parent.iterdir()] == ["T.0-0000-00.sqlite3"], "no temp left"


def test_a_missing_index_is_an_error_not_an_empty_result(home: Path) -> None:
    with pytest.raises(LibError, match="no index") as missing:
        index.search(SYNTHETIC, "widgets")
    assert missing.value.hint == "itu_info shows which editions are fetched"
    assert missing.value.action == "primarysource itu sync T.0#0000-00"


def test_an_itulib_index_file_is_refused_with_the_rebuild_command(home: Path) -> None:
    db = index._db_path(SYNTHETIC)
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as connection:  # the layout itulib wrote: no user_version, its own tables
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    with pytest.raises(LibError, match="schema version 0") as old:
        index.search(SYNTHETIC, "widgets")
    assert old.value.action == "primarysource itu index T.0#0000-00", "the command is a human's, so it is the action"


def test_an_extractor_that_finds_nothing_refuses_to_write_an_index(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(text, "pages", lambda _path: ["no numbered headings here"])
    with pytest.raises(LibError, match="0 clauses"):
        index.build(SYNTHETIC)
    assert not index._db_path(SYNTHETIC).exists()


def test_mcp_stdio_handshake_lists_eleven_text_tools_and_reports_a_missing_corpus(tmp_path: Path) -> None:
    """Drives the real server over stdio. Catches stdout pollution, which importing the module never would."""

    async def drive() -> tuple[dict[str, object], object, object]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "primarysource.itu.mcp"],
            env={**os.environ, "ITULIB_HOME": str(tmp_path)},
            cwd=Path(__file__).resolve().parents[2],
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name: tool.output_schema for tool in (await session.list_tools()).tools}
            info = await session.call_tool("itu_info", {})
            search = await session.call_tool("itu_search", {"query": "boolean"})
            return tools, info, search

    tools, info, search = anyio.run(drive)
    assert set(tools) == {
        "itu_info",
        "itu_search",
        "itu_read",
        "itu_outline",
        "itu_grep",
        "itu_errata",
        "itu_cite",
        "itu_links",
        "itu_browse",
        "itu_compare",
        "itu_catalog",
    }
    assert all(schema is None for schema in tools.values()), "text only: no tool advertises an output schema"
    assert not info.is_error and info.structured_content is None  # type: ignore[attr-defined]
    assert "not fetched" in info.content[0].text and "  fetched  " not in info.content[0].text  # type: ignore[attr-defined]
    assert search.is_error, "a missing corpus is an isError result, never an empty hit list"  # type: ignore[attr-defined]
    lines = search.content[0].text.splitlines()[1:]  # type: ignore[attr-defined]
    assert lines == [
        "error: X.690#2021-02: no index",
        "hint: itu_info shows which editions are fetched",
        "action: primarysource itu sync X.690#2021-02",
    ]


def test_mcp_without_the_extra_exits_2_with_the_install_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The first run of a core-only install crashed with a traceback from inside the SDK import, not this."""
    from primarysource.itu import cli

    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", None)
    assert cli.main(["mcp"]) == 2
    assert "primarysource[mcp]" in capsys.readouterr().err
