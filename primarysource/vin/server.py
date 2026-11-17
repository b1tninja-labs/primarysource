"""MCP server for the vin collection: `primarysource mcp --collection vin`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `vin_` prefix, answer
in text with the fixed footer, and turn a `LibError` into an MCP tool error. Every tool reads local files only;
none writes or fetches. The documents are GM's NHTSA filings, not an ISO designation and not a VIN decoder.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.scaffold import add_tools
from primarysource.vin import library

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "General Motors VIN standards filed with NHTSA under 49 CFR Part 565. "
    "Loop: vin_search('<words>') -> vin_read('<ref>'). "
    "Refs: 'vin:gm-vin-2016§33' is one PDF page; '¶n' starts at that line of the page. "
    "The filings do not give an ISO number. vin_docs lists what is imported. "
    "This collection does not decode a VIN."
)


def vin_read(ref: str, max_tokens: int = 2000) -> str:
    """Read one imported filing by ref, cut at line boundaries within max_tokens.

    ref: 'vin:gm-vin-2016' (the whole filing) | 'vin:gm-vin-2016§33' (one PDF page) |
      'vin:gm-vin-2016§33¶2' (from its 2nd line). A 'next:' footer line is the ref that continues."""
    return library.read(ref, max_tokens=max_tokens)


def vin_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find pages containing the query words (all of them, else any, flagged 'relaxed'), best first. One line per
    hit: '<ref>  <page title>: <snippet>'. doc restricts to one filing, e.g. 'gm-vin-2016'. A 'next: start=N'
    footer line means call again with start=N."""
    return library.search(query, doc=doc, limit=limit, start=start)


def vin_docs() -> str:
    """List the imported GM VIN filings and whether each source PDF is unchanged, changed or missing."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-vin", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (vin_read, vin_search, vin_docs), annotations=READ_ONLY)
    return built


server = _build()
