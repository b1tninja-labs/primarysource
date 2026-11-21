"""MCP server for the oid collection: `primarysource mcp --collection oid`.

Tools read the three root arcs from the imported X.660. Nothing here downloads.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.oid import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Root arcs of the international OID tree, from the imported Rec. ITU-T X.660 | ISO/IEC 9834-1. "
    "oid_roots lists arcs 0 (itu-t), 1 (iso) and 2 (joint-iso-itu-t). "
    "oid_read('0') is one arc. oid_export is the oid-node/1 JSON document for other languages. "
    "The cite line is the X.660 clause. Subordinate arcs are not loaded yet."
)


def oid_roots() -> str:
    """Arcs 0, 1 and 2, one per line. The cite line is the X.660 clause that assigns them."""
    return library.roots()


def oid_read(ref: str) -> str:
    """One root arc. ref: '0' | '1' | '2' | 'oid:0'."""
    return library.read(ref)


def oid_export() -> str:
    """The oid-node/1 JSON document for arcs 0, 1 and 2. A cite footer follows the JSON."""
    from primarysource.render import render

    nodes = library.root_nodes()
    return render(library.export().rstrip("\n"), {"cite": nodes[0].cite})


def _build() -> Any:
    built = MCPServer("primarysource-oid", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (oid_roots, oid_read, oid_export), annotations=READ_ONLY)
    return built


server = _build()
