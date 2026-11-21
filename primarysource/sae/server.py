"""MCP server for the sae collection. Tools read the local extraction only."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.sae import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "SAE documents from the user's own PDFs. Loop: sae_search('<words>') -> sae_read('<ref>'). "
    "Refs: 'sae:j2534@2002§5' (a clause), '...¶2' (from its 2nd sentence), 'j2534' means the newest imported "
    "year. sae_outline lists clauses; sae_cite gives the citation. If nothing is imported, the error says how."
)


def sae_read(ref: str, max_tokens: int = 2000) -> str:
    """Read an imported SAE document by ref."""
    return library.read(ref, max_tokens=max_tokens)


def sae_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find clauses containing the query words."""
    return library.search(query, doc=doc, limit=limit, start=start)


def sae_outline(doc: str, start: int = 0, limit: int = 200) -> str:
    """List an imported document's clauses as refs."""
    return library.outline(doc, start=start, limit=limit)


def sae_cite(ref: str) -> str:
    """The citation for a ref, with the hash of the cited text."""
    return library.cite(ref)


def sae_docs() -> str:
    """List what is imported."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-sae", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (sae_read, sae_search, sae_outline, sae_cite, sae_docs), annotations=READ_ONLY)
    return built


server = _build()
