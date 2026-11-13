"""The MCP contract of PLAN.md §5.9-5.12, as `primarysource mcp` serves it: errors, text only, tool names, and
several collections in one process. Calls go through the SDK's in-process client, so what is checked is what a
client receives, not what a tool function returns."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from primarysource import cli, registry, scaffold, serve
from primarysource.errors import LibError

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402


def _call(server: Any, name: str, arguments: dict[str, Any] | None = None) -> Any:
    import anyio

    async def drive() -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(drive)


def _names(server: Any) -> list[str]:
    import anyio

    async def drive() -> list[str]:
        async with Client(server) as client:
            return [tool.name for tool in (await client.list_tools()).tools]

    return anyio.run(drive)


def _source(tools: Sequence[Callable[..., Any]], *, structured: bool | None = False) -> Any:
    """A collection's own server, registered the way an older collection did (no guard, any structured_output)."""
    server = MCPServer("source", instructions="Source instructions.")
    for fn in tools:
        server.add_tool(fn, structured_output=structured)
    return server


def _served(name: str, *tools: Callable[..., Any], server: Any = None) -> scaffold.Served:
    return scaffold.Served(name, f"{name} title", server if server is not None else _source(tools))


# --- cl.mcp_error_contract -------------------------------------------------------------------------------------


def test_a_lib_error_reaches_the_client_as_is_error_with_the_fixed_lines() -> None:
    def read(ref: str) -> str:
        raise LibError(f"{ref} is not imported", "demo_status", "primarysource demo import")

    result = _call(scaffold.compose([_served("demo", read)]), "demo_read", {"ref": "D1"})
    assert result.is_error is True
    lines = result.content[0].text.splitlines()
    # the SDK's own first line names the tool; the contract's lines follow, each at the start of a line
    assert lines[0].startswith("Error executing tool demo_read")
    assert lines[1:] == ["error: D1 is not imported", "hint: demo_status", "action: primarysource demo import"]


def test_an_empty_field_is_left_out_and_the_order_is_fixed() -> None:
    assert LibError("no index", action="x index").as_text() == "error: no index\naction: x index"
    assert LibError("no index", "x_status", "x index").as_text().splitlines() == [
        "error: no index",
        "hint: x_status",
        "action: x index",
    ]


def test_an_empty_result_is_not_an_error() -> None:
    def search(query: str) -> str:
        return f"no section matches {query!r}\n"

    result = _call(scaffold.compose([_served("demo", search)]), "demo_search", {"query": "zebra"})
    assert result.is_error is False
    assert result.content[0].text == "no section matches 'zebra'\n"


def test_guard_covers_async_tools_and_add_tools_registers_guarded_text_tools() -> None:
    async def lookup(ref: str) -> str:
        raise LibError("bad ref", "demo_list")

    server = MCPServer("demo")
    scaffold.add_tools(server, [lookup], prefix="demo_")
    result = _call(server, "demo_lookup", {"ref": "x"})
    assert result.is_error is True
    assert result.content[0].text.splitlines()[1:] == ["error: bad ref", "hint: demo_list"]
    once = scaffold.guard(lookup)
    assert scaffold.guard(once) is once  # composing a server whose tools are already guarded adds no layer


def test_a_real_collection_served_by_primarysource_mcp_follows_the_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))  # nothing imported
    result = _call(cli.build_server(["usbids"]), "usbids_lookup", {"ref": "usbids:0001"})
    assert result.is_error is True
    lines = result.content[0].text.splitlines()[1:]
    assert lines[0].startswith("error: ") and "not imported" in lines[0]
    assert lines[1:] == ["action: primarysource usbids import"]  # a command only a person can run


# --- cl.structured_output_off -----------------------------------------------------------------------------------


def test_no_composed_tool_returns_structured_content() -> None:
    def counts(doc: str) -> dict[str, int]:
        return {"sections": 3}

    def title(doc: str) -> str:
        return "A title"

    # registered with structured output on, as an unconverted collection might do
    source = _source([counts, title], structured=None)
    assert any(tool.output_schema for tool in source._tool_manager.list_tools())
    server = scaffold.compose([_served("demo", server=source)])
    for name in ("demo_counts", "demo_title"):
        result = _call(server, name, {"doc": "D1"})
        assert result.structured_content is None, name
        assert result.content and result.content[0].type == "text"


def test_every_registered_collection_is_served_without_an_output_schema() -> None:
    server = cli.build_server(registry.available())
    tools = server._tool_manager.list_tools()
    assert tools
    assert [tool.name for tool in tools if tool.output_schema is not None] == []


def test_add_tools_never_publishes_an_output_schema() -> None:
    def counts(doc: str) -> dict[str, int]:
        return {"sections": 3}

    server = MCPServer("demo")
    scaffold.add_tools(server, [counts], prefix="demo_")
    assert server._tool_manager.get_tool("demo_counts").output_schema is None
    assert _call(server, "demo_counts", {"doc": "D1"}).structured_content is None


# --- cl.tool_prefix ---------------------------------------------------------------------------------------------


def test_primarysource_mcp_prefixes_every_tool_and_prompt() -> None:
    server = cli.build_server(["rfc"])
    names = _names(server)
    assert {"rfc_search", "rfc_read", "rfc_cite"} <= set(names)
    assert all(name.startswith("rfc_") for name in names)
    prompts = [prompt.name for prompt in server._prompt_manager.list_prompts()]
    assert prompts and all(name.startswith("rfc_") for name in prompts)
    # a collection whose tools already carry the prefix keeps them as they are, not "bbf_bbf_read"
    assert set(_names(cli.build_server(["bbf"]))) == {"bbf_read", "bbf_search", "bbf_outline", "bbf_cite", "bbf_docs"}


def test_bare_names_keep_the_collections_own_names() -> None:
    names = set(_names(cli.build_server(["rfc"], bare=True)))
    assert {"search", "read", "cite"} <= names
    assert not any(name.startswith("rfc_") for name in names)


def test_rfclib_mcp_still_serves_the_bare_names(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("typer")
    from primarysource.rfc import cli as rfc_cli

    seen: dict[str, Any] = {}
    monkeypatch.setattr(serve, "run", lambda server, transport, **kw: seen.update(server=server))
    monkeypatch.setenv("RFCLIB_READONLY", "")
    rfc_cli.mcp(transport="stdio", host="127.0.0.1", port=1, allowed_host=[], read_only=False)
    names = set(_names(seen["server"]))
    assert {"search", "read", "cite", "outline", "grep", "links", "info", "browse", "errata"} <= names


def test_the_cli_flag_selects_bare_names(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(serve, "run", lambda server, transport, **kw: seen.update(server=server))
    assert cli.main(["mcp", "--collection", "rfc", "--bare-names"]) == 0
    assert "search" in _names(seen["server"])
    assert cli.main(["mcp", "--collection", "rfc"]) == 0
    assert "rfc_search" in _names(seen["server"])


# --- cl.multi_collection_server ---------------------------------------------------------------------------------


def _homed(name: str, home: Path) -> scaffold.Served:
    def where() -> str:
        return str(home)

    return _served(name, where)


def test_several_collections_share_one_process_each_with_its_own_state(tmp_path: Path) -> None:
    server = scaffold.compose([_homed("alpha", tmp_path / "alpha"), _homed("beta", tmp_path / "beta")])
    assert sorted(_names(server)) == ["alpha_where", "beta_where"]
    assert _call(server, "alpha_where").content[0].text == str(tmp_path / "alpha")
    assert _call(server, "beta_where").content[0].text == str(tmp_path / "beta")
    assert "[alpha]" in server.instructions and "[beta]" in server.instructions


def test_the_cli_serves_every_named_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(serve, "run", lambda server, transport, **kw: seen.update(server=server))
    assert cli.main(["mcp", "--collection", "cavp", "--collection", "usbids", "--collection", "cavp"]) == 0
    names = _names(seen["server"])
    assert {name.split("_")[0] for name in names} == {"cavp", "usbids"}
    assert len(names) == len(set(names)) == 5 + 4


def test_a_tool_name_clash_is_refused_at_startup() -> None:
    def search(query: str) -> str:
        return ""

    with pytest.raises(LibError, match="'search' is wanted by both 'alpha' and 'beta'"):
        scaffold.compose([_served("alpha", search), _served("beta", search)], bare=True)

    def alpha_search(query: str) -> str:
        return ""

    with pytest.raises(LibError, match="defines the tool 'alpha_search' twice"):
        scaffold.compose([_served("alpha", search, alpha_search)])


def test_a_route_or_resource_clash_is_refused_at_startup() -> None:
    def build(name: str) -> scaffold.Served:
        server = MCPServer(name)

        async def healthz(request: Any) -> Any:  # pragma: no cover - never served
            return None

        def text(ref: str) -> str:  # pragma: no cover - never read
            return ref

        # called, not used as decorators: the SDK's decorators are untyped
        server.custom_route("/healthz", methods=["GET"])(healthz)
        server.resource("demo://{ref}")(text)
        return scaffold.Served(name, name, server)

    with pytest.raises(LibError, match="resource template 'demo://{ref}'|HTTP route '/healthz"):
        scaffold.compose([build("alpha"), build("beta")])
    single = scaffold.compose([build("alpha")])
    assert [route.path for route in single._custom_starlette_routes] == ["/healthz"]
    assert [t.uri_template for t in single._resource_manager.list_templates()] == ["demo://{ref}"]


def test_the_cli_refuses_a_clash_with_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(serve, "run", lambda server, transport, **kw: None)
    assert cli.main(["mcp", "--collection", "nist", "--collection", "usb", "--bare-names"]) == 2
    err = capsys.readouterr().err
    assert "error: the tool 'search' is wanted by both 'nist' and 'usb'" in err
    assert "hint: drop --bare-names" in err
