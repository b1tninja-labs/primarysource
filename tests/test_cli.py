from __future__ import annotations

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
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)
    code = cli.main(["mcp", "--collection", "rfc", "--transport", "http", "--port", "9999", "--read-only"])
    assert code == 0
    collection = registry.load("rfc")
    assert seen["server"] is registry.attribute(collection, collection.server, "server")
    assert (seen["transport"], seen["port"], seen["host"]) == ("http", 9999, "127.0.0.1")
    import os

    assert os.environ.get("PRIMARYSOURCE_READONLY") == "1"
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)


def test_http_off_loopback_without_allowed_hosts_warns(capsys: pytest.CaptureFixture[str]) -> None:
    assert serve.transport_security("0.0.0.0", ()) is None  # noqa: S104
    assert "no authentication" in capsys.readouterr().err
    assert serve.transport_security("127.0.0.1", ()) is None
