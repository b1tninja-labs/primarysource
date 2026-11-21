"""MCP server for the msos collection: `primarysource mcp --collection msos`.

Tools answer in text with the fixed footer and read only the imported Open Specifications. Nothing here
downloads or writes.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.msos import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Microsoft Open Specifications (protocols, computer languages, standards support, and data portability), "
    "from the PDF zips linked on learn.microsoft.com. Loop: msos_search('<words>') -> msos_read('<ref>'). "
    "Refs: 'msos:ms-patch§2.1' (a clause), 'ms-cab', '[MS-CAB]'. msos_outline lists clauses; msos_cite gives "
    "the citation; msos_docs lists what is imported. Download with `primarysource msos sync`."
)


def msos_read(ref: str, max_tokens: int = 2000) -> str:
    """Read an Open Specification by ref, cut at sentence boundaries within max_tokens.

    ref: 'msos:ms-patch' | 'msos:ms-patch§2.1' | 'msos:ms-patch§2.1¶2' | '[MS-CAB]'. A 'next:' line is the
    ref that continues."""
    return library.read(ref, max_tokens=max_tokens)


def msos_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find clauses containing the query words (all of them, else any, flagged 'relaxed'), best first.
    doc restricts to one specification, e.g. 'ms-patch'. A 'next: start=N' line pages the hits."""
    return library.search(query, doc=doc, limit=limit, start=start)


def msos_outline(doc: str, start: int = 0, limit: int = 200) -> str:
    """List a specification's clauses, each with the ref that reads it. A 'next: start=N' line pages the list."""
    return library.outline(doc, start=start, limit=limit)


def msos_cite(ref: str) -> str:
    """The citation for a ref, with the sha256 prefix of the exact text cited."""
    return library.cite(ref)


def msos_docs() -> str:
    """List the imported Open Specifications and which document set each PDF came from."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-msos", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (msos_read, msos_search, msos_outline, msos_cite, msos_docs), annotations=READ_ONLY)
    return built


server = _build()
