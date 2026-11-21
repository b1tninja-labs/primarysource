"""MCP server for the bluetooth collection: `primarysource mcp --collection bluetooth`.

Tools answer in text with the fixed footer and read only the imported specifications. Nothing here downloads.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.bluetooth import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Bluetooth specifications from the catalog at bluetooth.com/specifications/specs/. "
    "Loop: bluetooth_search('<words>') -> bluetooth_read('<ref>'). "
    "Refs: 'bluetooth:battery-service§1.1' (a section), 'bluetooth:core-specification-7-0§4.E.1' "
    "(Core Specification volume 4, part E, section 1). bluetooth_outline lists sections; bluetooth_cite "
    "gives the citation; bluetooth_docs lists the catalog. Download with `primarysource bluetooth sync`."
)


def bluetooth_read(ref: str, max_tokens: int = 2000) -> str:
    """Read a specification by ref, cut at block boundaries within max_tokens.

    ref: 'bluetooth:battery-service' | 'bluetooth:battery-service§1.1' | 'bluetooth:battery-service§1.1¶2'.
    A 'next:' line is the ref that continues."""
    return library.read(ref, max_tokens=max_tokens)


def bluetooth_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find sections containing the query words (all of them, else any, flagged 'relaxed'), best first.
    doc restricts to one specification, e.g. 'battery-service'. A 'next: start=N' line pages the hits."""
    return library.search(query, doc=doc, limit=limit, start=start)


def bluetooth_outline(doc: str, start: int = 0, limit: int = 200) -> str:
    """List a specification's sections, each with the ref that reads it. A 'next: start=N' line pages the list."""
    return library.outline(doc, start=start, limit=limit)


def bluetooth_cite(ref: str) -> str:
    """The citation for a ref, with the sha256 prefix of the exact text cited."""
    return library.cite(ref)


def bluetooth_docs(start: int = 0, limit: int = 50) -> str:
    """List the catalog: version, status, whether the HTML book is imported, and the title."""
    return library.docs(start=start, limit=limit)


def _build() -> Any:
    built = MCPServer("primarysource-bluetooth", version=__version__, instructions=INSTRUCTIONS)
    add_tools(
        built,
        (bluetooth_read, bluetooth_search, bluetooth_outline, bluetooth_cite, bluetooth_docs),
        annotations=READ_ONLY,
    )
    return built


server = _build()
