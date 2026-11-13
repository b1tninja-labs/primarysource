from __future__ import annotations

import inspect
from typing import Any

import pytest

from primarysource import cli, registry, serve


def test_collections_lists_rfc(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["collections"]) == 0
    assert "rfc" in capsys.readouterr().out.split()


def test_an_unknown_collection_exits_2_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["mcp", "--collection", "nope"]) == 2
    assert "no collection named 'nope'" in capsys.readouterr().err


def test_an_unknown_transport_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["mcp", "--collection", "rfc", "--transport", "carrier-pigeon"]) == 2
    assert "unknown transport" in capsys.readouterr().err


def test_mcp_serves_the_collection_server(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    pytest.importorskip("typer")
    seen: dict[str, Any] = {}

    def fake_run(server: Any, transport: str, **kwargs: Any) -> None:
        seen.update(server=server, transport=transport, **kwargs)

    monkeypatch.setattr(serve, "run", fake_run)
    # setenv, not delenv: delenv of an absent variable records nothing to restore, so the "1" the CLI sets
    # would outlive this test and put every later test in read-only mode.
    monkeypatch.setenv("PRIMARYSOURCE_READONLY", "")
    code = cli.main(["mcp", "--collection", "rfc", "--transport", "http", "--port", "9999", "--read-only"])
    assert code == 0
    # the collection's own server, composed: the same functions under prefixed names
    collection = registry.load("rfc")
    own = registry.attribute(collection, collection.server, "server")
    served = {tool.name: tool for tool in seen["server"]._tool_manager.list_tools()}
    assert {f"rfc_{tool.name}" for tool in own._tool_manager.list_tools()} == set(served)
    assert inspect.unwrap(served["rfc_search"].fn) is inspect.unwrap(own._tool_manager.get_tool("search").fn)
    assert (seen["transport"], seen["port"], seen["host"]) == ("http", 9999, "127.0.0.1")
    import os

    assert os.environ.get("PRIMARYSOURCE_READONLY") == "1"


def test_http_off_loopback_without_allowed_hosts_warns(capsys: pytest.CaptureFixture[str]) -> None:
    assert serve.transport_security("0.0.0.0", ()) is None  # noqa: S104
    assert "no authentication" in capsys.readouterr().err
    assert serve.transport_security("127.0.0.1", ()) is None


def test_read_only_mode_does_not_leak_into_later_tests() -> None:
    # runs after test_mcp_serves_the_collection_server in file order
    import os

    assert os.environ.get("PRIMARYSOURCE_READONLY", "") == ""


def test_a_server_target_may_be_a_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver import MCPServer

    built: list[Any] = []

    def ping() -> str:
        return "pong"

    def factory() -> Any:
        server = MCPServer("factory-built")
        server.add_tool(ping)
        built.append(server)
        return server

    seen: dict[str, Any] = {}
    monkeypatch.setattr(serve, "run", lambda server, transport, **kw: seen.update(server=server))
    monkeypatch.setattr(registry, "attribute", lambda collection, spec, what: factory)
    assert cli.main(["mcp", "--collection", "rfc"]) == 0
    assert len(built) == 1
    assert seen["server"]._tool_manager.get_tool("rfc_ping").fn.__wrapped__ is ping
