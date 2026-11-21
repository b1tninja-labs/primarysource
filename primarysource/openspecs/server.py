"""MCP server for the Open Specifications collection: `primarysource mcp --collection openspecs`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `openspecs_` prefix,
answer in text with the fixed footer, and turn a `LibError` into an MCP tool error naming the remedy. Every tool
reads local files only; none writes or fetches.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.openspecs import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Microsoft Open Specifications published on Microsoft Learn (protocols, languages, standards support, "
    "and file formats). The container, MSZIP, Cabinet LZX and LZX DELTA are separate documents: [MS-MCI] is "
    "MSZIP, the 1997 Cabinet LZX chapter is not an [MS-*] page, and [MS-PATCH] is LZX DELTA. "
    "Loop: openspecs_search('<words>') -> openspecs_read('<ref>'). Refs: 'openspecs:MS-SMB2§2.2.1' (a Learn "
    "page), '...¶2' (its 2nd block). openspecs_outline('MS-SMB2') lists pages; openspecs_cite('<ref>') gives "
    "one block and its hash. If the catalog or a page is missing, the error names fetch or sync."
)


def openspecs_read(ref: str, max_tokens: int = 2000) -> str:
    """Read one Open Specifications page by ref, cut at block boundaries within max_tokens. A 'next: <ref>'
    footer line is the ref that reads the next blocks: pass it back as ref.

    ref: 'openspecs:MS-SMB2§2.2.1' | 'MS-SMB2§2.2.1¶2' (from its 2nd block). openspecs_cite gives exactly one
    block."""
    return library.read(ref, max_tokens=max_tokens)


def openspecs_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find pages containing the query words (all of them, else any, flagged 'relaxed'). One line per hit:
    '<ref>: <snippet>'. doc restricts to one specification, e.g. 'MS-SMB2'. A 'next: start=N' footer line means
    call again with start=N (a 0-based offset)."""
    return library.search(query, doc=doc, limit=limit, start=start)


def openspecs_outline(doc: str) -> str:
    """List one specification's Learn pages, indented by the table of contents, each with the ref that reads it."""
    return library.outline(doc)


def openspecs_cite(ref: str) -> str:
    """The citation string for one block, with the sha256 prefix of the exact text cited (cite: and span: lines)."""
    return library.cite(ref)


def openspecs_docs(start: int = 0, limit: int = 50) -> str:
    """List the catalogued specifications and how many of each specification's pages are stored."""
    return library.docs(start=start, limit=limit)


def _build() -> Any:
    built = MCPServer("primarysource-openspecs", version=__version__, instructions=INSTRUCTIONS)
    add_tools(
        built,
        (openspecs_read, openspecs_search, openspecs_outline, openspecs_cite, openspecs_docs),
        annotations=READ_ONLY,
    )
    return built


server = _build()
