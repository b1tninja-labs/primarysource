"""MCP server for the iso collection: `primarysource mcp --collection iso`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `iso_` prefix, answer
in text with the fixed footer, and turn a `LibError` into an MCP tool error with `error:`/`hint:`/`action:` lines.
Every tool reads local files only; none writes or fetches. Serve it on the buyer's own machine (stdio, or a
container with the iso home mounted read-only): the PDFs behind it are single-user copies.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.iso import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "ISO standards from the user's own purchased PDFs. Loop: iso_search('<words>') -> iso_read('<ref>'). "
    "Refs: 'iso:9899@2024§6.5.2' (a clause as numbered in the PDF), '...¶3' (from its 3rd sentence), '9899' means "
    "the newest imported year, 'A' is Annex A; 'ISO/IEC 9899:2024§6.5.2' works too. iso_outline('9899') lists "
    "clauses as refs; iso_cite('<ref>') gives the citation and the hash of the cited text. iso_docs lists what is "
    "imported. If a standard is not imported, the error says what the user must do. When Ecma states an edition "
    "is fully identical with that standard, the error names the ecma: ref and the hint is ecma_read."
)


def iso_read(ref: str, max_tokens: int = 2000) -> str:
    """Read ISO text by ref, cut at sentence boundaries within max_tokens. A 'next: <ref>' footer line is the ref
    that reads the next page: pass it back as ref.

    ref: 'iso:9899@2024' (whole standard) | 'iso:9899@2024§6.5.2' (a clause and its subsections) |
      'iso:9899@2024§6.5.2¶3' (from its 3rd sentence) | 'ISO/IEC 9899:2024§A'. iso_cite gives exactly one sentence."""
    return library.read(ref, max_tokens=max_tokens)


def iso_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find clauses containing the query words (all of them, else any, flagged 'relaxed'), best first. One line per
    hit: '<ref>  <clause title>: <snippet>'. doc restricts to one standard, e.g. '9899' or '9899@2024'. A
    'next: start=N' footer line means call again with start=N (a 0-based offset)."""
    return library.search(query, doc=doc, limit=limit, start=start)


def iso_outline(doc: str, start: int = 0, limit: int = 200) -> str:
    """List a standard's clauses, indented by depth, each with the ref that reads it and its PDF page. A
    'next: start=N' footer line means call again with start=N."""
    return library.outline(doc, start=start, limit=limit)


def iso_cite(ref: str) -> str:
    """The citation string for a ref, with the sha256 prefix of the exact text cited (cite: and span: lines)."""
    return library.cite(ref)


def iso_docs() -> str:
    """List the imported ISO standards and whether each source PDF is unchanged, changed or missing."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-iso", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (iso_read, iso_search, iso_outline, iso_cite, iso_docs), annotations=READ_ONLY)
    return built


server = _build()
