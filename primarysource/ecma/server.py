"""MCP server for the ecma collection: `primarysource mcp --collection ecma`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `ecma_` prefix,
answer in text with the fixed footer, and turn a `LibError` into an MCP tool error naming the remedy. Every tool
reads local files only; none writes or fetches.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.ecma import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Ecma International standards from the user's own imported PDFs, starting with ECMA-427 (Package-URL / purl). "
    "Loop: ecma_search('<words>') -> ecma_read('<ref>'). Refs: 'ecma:427§5.3' (a clause as numbered in the PDF), "
    "'...¶2' (its 2nd sentence), '427@1' pins the edition, 'A' is Annex A. ecma_outline('427') lists clauses as "
    "refs with PDF pages; ecma_cite('<ref>') gives the citation and the hash of the cited text. A clause's span is "
    "its own text and then each subsection. If nothing is imported, the error says how."
)


def ecma_read(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read Ecma text by ref, cut at sentence boundaries within max_tokens. A 'next: start=N' footer line means
    call again with start=N.

    ref: 'ecma:427' (whole standard) | 'ecma:427§5.3' (a clause and its subsections) | 'ecma:427§5.3¶2' (one
      sentence) | '427@1§A' (edition 1, Annex A)."""
    return library.read(ref, start=start, max_tokens=max_tokens)


def ecma_search(query: str, doc: str | None = None, limit: int = 10, start: int = 1) -> str:
    """Find sentences containing the query words (all of them, else at least half, flagged 'relaxed'). One line
    per hit: '<ref>¶n: <snippet>'. doc restricts to one standard, e.g. '427'. A 'next: start=N' footer resumes."""
    return library.search(query, doc=doc, limit=limit, start=start)


def ecma_outline(doc: str) -> str:
    """List a standard's clauses, indented by depth, each with the ref that reads it and its PDF page."""
    return library.outline(doc)


def ecma_cite(ref: str) -> str:
    """The citation string for a ref, with the sha256 prefix of the exact text cited (cite: and span: lines)."""
    return library.cite(ref)


def ecma_docs() -> str:
    """List the catalogued Ecma standards and whether each is imported."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-ecma", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (ecma_read, ecma_search, ecma_outline, ecma_cite, ecma_docs), annotations=READ_ONLY)
    return built


server = _build()
