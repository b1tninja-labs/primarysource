"""rfc under the core MCP contract (PLAN.md §5.10, §5.12), as a client of
`primarysource mcp` sees it: anticipated failures are isError results of
`error:` / `hint:` / `action:` lines (the tool to call next in hint, the
command a human runs in action), an empty result is not an error, and the
completion handler for document ids and sections survives `compose`."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402
from mcp import Client  # noqa: E402
from mcp.types import PromptReference, ResourceTemplateReference  # noqa: E402

from primarysource import cli  # noqa: E402


def _call(name, arguments):
    async def drive():
        async with Client(cli.build_server(["rfc"])) as client:
            return await client.call_tool(name, arguments)
    return anyio.run(drive)


def _error_lines(result) -> dict[str, str]:
    """The contract's lines of an isError result, by field; the SDK's own
    first line ('Error executing tool ...') is not one of them."""
    assert result.is_error is True
    lines = result.content[0].text.splitlines()
    assert lines[0].startswith("Error executing tool")
    fields = dict(line.split(": ", 1) for line in lines[1:])
    assert list(fields) == [k for k in ("error", "hint", "action")
                            if k in fields], lines
    return fields


def test_an_empty_library_names_rfclib_init_as_the_action(home):
    fields = _error_lines(_call("rfc_search", {"query": "tls"}))
    assert "is empty" in fields["error"]
    assert "hint" not in fields
    assert fields["action"].startswith("rfclib init")


def test_a_bad_ref_gets_the_ref_forms_as_its_hint(library):
    fields = _error_lines(_call("rfc_read", {"ref": "not a ref"}))
    assert fields["error"] == "can't parse ref 'not a ref'"
    assert fields["hint"].startswith("ref forms: 'RFC9000'")
    assert "action" not in fields


def test_a_missing_section_hints_the_outline_tool(library):
    fields = _error_lines(_call("rfc_read", {"ref": "RFC768§99"}))
    assert fields["error"].startswith("no section 99 in RFC768")
    assert fields["hint"] == "outline('RFC768')"


def test_read_only_and_not_indexed_puts_the_command_in_action(library,
                                                             monkeypatch):
    monkeypatch.setenv("RFCLIB_READONLY", "1")
    fields = _error_lines(_call("rfc_read", {"ref": "RFC2119"}))
    assert "read-only" in fields["error"]
    assert fields["hint"] == "read it through the shared rfclib server once"
    assert fields["action"] == "rfclib sync && rfclib index build"


def test_a_read_only_server_without_a_library_says_so(home, monkeypatch):
    monkeypatch.setenv("RFCLIB_READONLY", "1")
    fields = _error_lines(_call("rfc_search", {"query": "anything"}))
    assert "existing library" in fields["error"]
    assert fields["action"].startswith("rfclib init")
    assert not home.exists()


def test_an_empty_search_is_not_an_error(library):
    result = _call("rfc_search", {"query": "zzzqqqxyzzy", "mode": "exact"})
    assert result.is_error is False


def test_completions_reach_rfc_through_the_prefixed_server(library):
    conn, _ = library
    from primarysource.rfc import library as lib
    assert lib.ensure_indexed(conn, "RFC5234")
    conn.commit()

    async def drive():
        async with Client(cli.build_server(["rfc"])) as client:
            prompt = PromptReference(type="ref/prompt", name="rfc_explain")
            docs = await client.complete(prompt, {"name": "ref",
                                                  "value": "RFC52"})
            secs = await client.complete(
                ResourceTemplateReference(type="ref/resource",
                                          uri="rfc://{ref}"),
                {"name": "ref", "value": "RFC5234§"})
            return docs.completion.values, secs.completion.values

    docs, secs = anyio.run(drive)
    assert "RFC5234" in docs
    assert secs and all(v.startswith("RFC5234§") for v in secs)
