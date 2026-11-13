"""MCP server for the iana collection: `primarysource mcp --collection iana`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the prefix `iana_`, answer
in text with the fixed footer, and turn a `LibError` into an MCP tool error naming the remedy. Every tool reads local
files only; none writes or fetches (importing is `primarysource iana import`).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.iana import reader
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "IANA protocol registries (DNS, DHCP, BGP, STUN, TLS, HTTP, ...) from the user's imported copies of the XML "
    "at iana.org/assignments, which is CC0. Registry values are authoritative data: use iana_lookup for 'what is "
    "DHCP option 53' and iana_search to find a registry. Refs: 'dns-parameters' (the file's registries), "
    "'dns-parameters§dns-parameters-4' (one registry), 'bgp-parameters§bgp-parameters-2#3' (the record with value "
    "3), '...¶4' (the 4th record). Each row carries its RFC citations (RFC4271§4.3 reads in the rfc collection). "
    "The cite: footer line is the citation. If a registry is not imported the error says how."
)


def iana_read(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read an IANA registry by ref, cut at record boundaries within max_tokens ('next: start=N' continues).

    ref: 'dns-parameters' (list its registries) | 'dns-parameters§dns-parameters-4' (a registry: procedure,
      notes, then records) | 'bgp-parameters§bgp-parameters-2#3' (records whose value is 3) |
      'bgp-parameters§bgp-parameters-2¶4' (the 4th record). 'dns-parameters#dns-parameters-4' also works."""
    return reader.read(ref, start=start, max_tokens=max_tokens)


def iana_lookup(registry: str, value: str) -> str:
    """The record(s) with a value in a registry, e.g. registry 'bootp-dhcp-parameters§message-type-53', value '5'.
    registry may be just a file name ('dns-parameters') to try every registry in it. A number matches a record whose
    value is that number or a range containing it (decimal or 0x hex); text matches a value or a column exactly,
    ignoring case ('A' finds RR type A)."""
    return reader.lookup(registry, value)


def iana_search(text: str, file: str | None = None, limit: int = 20, start: int = 1) -> str:
    """Find records whose registry title and columns contain every word of text (case-insensitive, literal, at most
    200 characters). file: restrict to one registry file, e.g. 'stun-parameters'. One line per hit:
    '<ref>  <registry>: <record>'. A 'next: start=N' footer resumes."""
    return reader.search(text, file=file, limit=limit, start=start)


def iana_list() -> str:
    """The catalogue of registries this collection knows, each marked imported or not, with its updated date."""
    return reader.listing()


def _server() -> Any:
    server = MCPServer("primarysource-iana", version=__version__, instructions=INSTRUCTIONS)
    add_tools(server, (iana_read, iana_lookup, iana_search, iana_list), annotations=READ_ONLY)
    return server


server = _server()
