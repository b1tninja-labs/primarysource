"""The draft collection behind the core's `primarysource` command and MCP server."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from draft_fixture import NAME, Clock, DraftSpec, FakeIetf

from primarysource import cli, registry
from primarysource.draft import cli as draft_cli
from primarysource.draft.collection import COLLECTION
from primarysource.draft.net import Fetcher

FAR = "2099-01-01 00:00:00"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)
    fake = FakeIetf(
        DraftSpec(expires=FAR),
        DraftSpec(name="draft-example-gone-proto", state="Expired", expires="2014-01-01 00:00:00"),
    )
    clock = Clock()
    monkeypatch.setattr(draft_cli, "fetcher_factory", lambda: Fetcher(fake, clock=clock.clock, sleep=clock.sleep))
    return tmp_path


def test_the_collection_is_found_by_name_with_its_prefix_and_grammar() -> None:
    assert "draft" in registry.available()
    found = registry.load("draft")
    assert found is COLLECTION
    assert (found.prefix, found.unit.value) == ("draft_", "paragraph")
    ref = found.grammar.parse("draft-ietf-sidrops-8210bis-17§5.1¶2")
    assert (ref.doc, ref.section, ref.para) == ("draft-ietf-sidrops-8210bis-17", "5.1", 2)


def test_the_command_imports_then_reads_outlines_searches_cites_and_lists(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["draft", "import", NAME, "--print-pin"]) == 0
    out = capsys.readouterr().out
    assert f"{NAME}-03: imported" in out and "not pinned (trusted on first use)" in out and "5 requests" in out
    assert '"txt":' in out  # the digest to paste into tracked.json
    assert (home / "draft" / NAME / "03" / "meta.json").is_file()
    assert cli.main(["draft", "import", NAME]) == 0
    assert "already stored" in capsys.readouterr().out
    assert cli.main(["draft", "list"]) == 0
    assert f"{NAME}  stored: -03" in capsys.readouterr().out
    assert cli.main(["draft", "outline", NAME]) == 0
    assert f"{NAME}-03§2.1  2.1 Messages  (3)" in capsys.readouterr().out
    assert cli.main(["draft", "read", f"{NAME}§2.2"]) == 0
    read = capsys.readouterr().out
    assert "A retransmission timer runs" in read and "latest stored revision -03" in read
    assert cli.main(["draft", "search", "retransmission"]) == 0
    assert f"{NAME}-03§2.2" in capsys.readouterr().out
    assert cli.main(["draft", "cite", f"{NAME}-03§2.2¶1"]) == 0
    assert "Work in Progress, Internet-Draft" in capsys.readouterr().out
    assert cli.main(["draft", "info", NAME]) == 0
    assert "standing: ACTIVE" in capsys.readouterr().out


def test_refresh_reports_state_and_a_failed_draft_does_not_stop_the_rest(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["draft", "refresh", NAME, "draft-example-gone-proto"]) == 0
    out = capsys.readouterr().out
    assert f"{NAME}: latest -03, state Active" in out
    assert "draft-example-gone-proto: latest -03, state Expired" in out
    assert cli.main(["draft", "refresh", "draft-nobody-nothing", NAME]) == 1
    captured = capsys.readouterr()
    assert "has no draft named draft-nobody-nothing" in captured.err
    assert f"{NAME}: latest -03" in captured.out


def test_import_needs_a_name_or_tracked_and_a_digest_needs_one_explicit_revision(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["draft", "import"]) == 1
    assert "name a draft, or pass --tracked" in capsys.readouterr().err
    assert cli.main(["draft", "import", NAME, "--sha256", "0" * 64]) == 1
    assert "needs exactly one draft with an explicit revision" in capsys.readouterr().err
    assert cli.main(["draft", "import", f"{NAME}-03", "--sha256", "0" * 64]) == 1
    assert "nothing was stored" in capsys.readouterr().err


def test_errors_name_their_remedy_and_exit_nonzero(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["draft", "read", f"{NAME}-03§1"]) == 1
    err = capsys.readouterr().err
    assert "error:" in err and f"action: primarysource draft import {NAME}-03" in err
    assert cli.main(["draft", "info", "draft-nobody-nothing"]) == 1
    assert cli.main(["draft", "search", "word"]) == 1


def test_read_only_refuses_the_commands_that_fetch(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["draft", "import", NAME]) == 0
    capsys.readouterr()
    monkeypatch.setenv("PRIMARYSOURCE_READONLY", "1")
    assert cli.main(["draft", "refresh", NAME]) == 1
    assert "read-only" in capsys.readouterr().err
    assert cli.main(["draft", "read", f"{NAME}-03§1¶1"]) == 0  # reading is what a read-only volume is for


def test_a_read_only_volume_can_still_be_read_when_the_cache_is_missing(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["draft", "import", NAME]) == 0
    (home / "draft" / NAME / "03" / "sections.json").unlink()
    monkeypatch.setenv("PRIMARYSOURCE_READONLY", "1")
    assert cli.main(["draft", "outline", NAME]) == 0
    assert not (home / "draft" / NAME / "03" / "sections.json").exists()  # nothing written


def test_the_server_lists_the_prefixed_tools_with_read_only_annotations() -> None:
    pytest.importorskip("mcp")
    server = registry.attribute(COLLECTION, COLLECTION.server, "server")
    tools = asyncio.run(server.list_tools())
    assert [t.name for t in tools] == [
        "draft_read",
        "draft_outline",
        "draft_search",
        "draft_cite",
        "draft_info",
        "draft_list",
    ]
    assert all(t.annotations is not None and t.annotations.read_only_hint for t in tools)
    assert all(t.name.startswith(COLLECTION.prefix) for t in tools)


def test_a_tool_answers_text_with_the_banner_and_a_failure_names_the_remedy(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from primarysource.draft.server import server

    with pytest.raises(ToolError, match=f"action: primarysource draft import {NAME}"):
        asyncio.run(server.call_tool("draft_read", {"ref": f"{NAME}§1"}))
    assert cli.main(["draft", "import", "draft-example-gone-proto"]) == 0
    result = str(asyncio.run(server.call_tool("draft_read", {"ref": "draft-example-gone-proto§1¶1"})))
    assert "[EXPIRED: expired on 2014-01-01" in result
    assert "warning: no revision in the ref" in result
    info = str(asyncio.run(server.call_tool("draft_info", {"name": "draft-example-gone-proto"})))
    assert "standing: EXPIRED" in info
    listed = str(asyncio.run(server.call_tool("draft_list", {})))
    assert "draft-example-gone-proto  stored: -03" in listed
    with pytest.raises(ToolError, match="not a ref"):
        asyncio.run(server.call_tool("draft_read", {"ref": "RFC9000"}))


def test_the_server_never_fetches_or_writes(home: Path) -> None:
    pytest.importorskip("mcp")
    import primarysource.draft.server as served

    names = set(dir(served))
    assert "importer" not in names and "fetcher_factory" not in names and "net" not in names


def test_import_tracked_takes_every_catalogued_draft_at_its_latest_revision(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from primarysource.draft import catalogue

    tracked = catalogue.Tracked(NAME, "why", (), "", "", (), None, "", "", {})
    monkeypatch.setattr(catalogue, "TRACKED", {NAME: tracked})
    assert cli.main(["draft", "import", "--tracked", "--no-xml"]) == 0
    assert f"{NAME}-03: imported" in capsys.readouterr().out
    assert cli.main(["draft", "refresh", "--tracked"]) == 0
    assert f"{NAME}: latest -03" in capsys.readouterr().out
