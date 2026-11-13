"""MCP server for the c2sp collection: `primarysource mcp --collection c2sp`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `c2sp_` prefix,
answer in text with the fixed footer, and turn a `LibError` into an MCP tool error naming the remedy. Every tool
reads local files only; none writes or fetches.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.c2sp import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "C2SP specifications (CC BY 4.0) at a pinned commit: static-ct-api, tlog-tiles, tlog-checkpoint, signed-note, "
    "and the rest of the C2SP repository's top-level documents. Loop: c2sp_search('<words>') -> c2sp_read('<ref>'). "
    "Refs: 'static-ct-api§Log Entries' (a heading by its text or slug), '...¶2' (its 2nd block), "
    "'static-ct-api@09f3e51§...' to pin a commit. c2sp_outline('<doc>') lists headings as refs; c2sp_cite('<ref>') "
    "gives the citation and the hash of the cited text. If nothing is imported, the error says how."
)


def c2sp_read(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read C2SP text by ref, cut at block boundaries within max_tokens. A 'next: start=N' footer line means call
    again with start=N.

    ref: 'static-ct-api' (whole document) | 'static-ct-api§Log Entries' (a section, subsections included) |
      '...§Log Entries¶2' (one block) | 'static-ct-api@09f3e51§...' (pinned commit). A 'c2sp:' prefix is allowed."""
    return library.read(ref, start=start, max_tokens=max_tokens)


def c2sp_search(query: str, doc: str | None = None, limit: int = 10, start: int = 1) -> str:
    """Find blocks containing the query words (all of them, else at least half, flagged 'relaxed'). One line per
    hit: '<ref>¶n: <snippet>'. doc restricts to one specification. A 'next: start=N' footer resumes."""
    return library.search(query, doc=doc, limit=limit, start=start)


def c2sp_outline(doc: str) -> str:
    """List a specification's headings, indented by level, each with the ref that reads it. doc: 'tlog-tiles'."""
    return library.outline(doc)


def c2sp_cite(ref: str) -> str:
    """The citation string for a ref, with the sha256 prefix of the exact text cited (cite: and span: lines)."""
    return library.cite(ref)


def c2sp_docs() -> str:
    """List the catalogued specifications and whether each is imported."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-c2sp", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (c2sp_read, c2sp_search, c2sp_outline, c2sp_cite, c2sp_docs), annotations=READ_ONLY)
    return built


server = _build()
