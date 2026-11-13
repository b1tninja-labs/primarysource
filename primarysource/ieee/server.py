"""MCP servers for the posix and ieee802 collections: `primarysource mcp --collection posix` (or `ieee802`).

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the collection's prefix
(`posix_read`, `ieee802_outline`), answer in text with the fixed footer, and turn a `LibError` into an MCP tool
error (`isError`) whose text names the remedy. Every tool reads local files only; none writes or fetches.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.errors import LibError
from primarysource.ieee import ieee802, posix

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

POSIX_INSTRUCTIONS = (
    "POSIX: IEEE Std 1003.1-2024, the same text as The Open Group Base Specifications Issue 8, from the user's "
    "own imported copy of the HTML edition. Pages are addressed by path: functions/open (XSH), utilities/pax "
    "(XCU), basedefs/stdio.h and basedefs/V1_chap03 (XBD), xrat/... (rationale). Loop: posix_grep('<words>') or "
    "posix_outline('<page>') -> posix_read('<ref>'). Refs: 'posix-2024§functions/open' (page), "
    "'posix-2024§functions/open#tag_17_372_03' (a heading's anchor), '...¶2' (the 2nd block under it). The "
    "cite: footer line is the citation. If the edition is not imported, the error says how."
)
IEEE802_INSTRUCTIONS = (
    "IEEE 802 standards from PDFs the user obtained through the IEEE GET Program and imported. "
    "ieee802_outline('802.1Q-2022') lists clauses as refs ('802.1Q-2022§5.4') with their PDF pages. Reading "
    "clause text is not built yet."
)


def _guard(fn: Callable[..., str]) -> Callable[..., str]:
    """Run a tool, turning a LibError into a tool error with its hint."""

    @functools.wraps(fn)  # the SDK reads the tool's schema from the wrapped signature
    def wrapped(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except LibError as exc:
            raise ToolError(exc.as_text()) from None

    return wrapped


def posix_read(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read POSIX text by ref, cut at block boundaries within max_tokens. A 'next: start=N' footer line means
    call again with start=N.

    ref: 'posix-2024§functions/open' (whole page) | 'posix-2024§functions/open#tag_17_372_03' (one heading's
      section, subsections included) | '...#tag_17_372_03¶2' (one block). 'functions/open' alone also works."""
    return posix.read(ref, start=start, max_tokens=max_tokens)


def posix_outline(page: str) -> str:
    """List a POSIX page's headings, each with the ref that reads it. page: 'functions/open', 'utilities/pax',
    'basedefs/V1_chap03'."""
    return posix.outline(page)


def posix_grep(text: str, volume: str | None = None, limit: int = 20, start: int = 1) -> str:
    """Find blocks containing text (case-insensitive, literal, at most 200 characters). One line per hit:
    '<ref>: <snippet>'. volume: functions | utilities | basedefs | xrat. A 'next: start=N' footer resumes."""
    return posix.grep(text, volume=volume, limit=limit, start=start)


def posix_pages(volume: str | None = None) -> str:
    """List page ids, optionally of one volume: functions (XSH), utilities (XCU), basedefs (XBD), xrat."""
    return "\n".join(posix.pages(volume)) or "no pages"


def ieee802_outline(designation: str) -> str:
    """List an imported 802 standard's clauses from its PDF bookmarks. designation: '802.1Q-2022'."""
    return ieee802.outline(designation)


def _server(name: str, instructions: str, tools: list[Callable[..., str]]) -> Any:
    server = MCPServer(name, version=__version__, instructions=instructions)
    for tool in tools:
        server.add_tool(_guard(tool), name=tool.__name__, annotations=READ_ONLY, structured_output=False)
    return server


posix_server = _server(
    "primarysource-posix", POSIX_INSTRUCTIONS, [posix_read, posix_outline, posix_grep, posix_pages]
)
ieee802_server = _server("primarysource-ieee802", IEEE802_INSTRUCTIONS, [ieee802_outline])
