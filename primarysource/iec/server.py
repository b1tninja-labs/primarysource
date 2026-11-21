"""MCP server for the iec collection: `primarysource mcp --collection iec`.

Imported only when served, so `mcp` is needed only then. Tools carry the `iec_` prefix, answer in text with the
fixed footer, and turn a `LibError` into an MCP tool error. Every tool reads local files only; none writes or
fetches. ISO and ISO/IEC editions are served by the iso collection.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.iec import library
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "IEC publications from the user's own downloads, other than ISO and ISO/IEC editions (those are iso_*). "
    "Loop: iec_search('<words>') -> iec_read('<ref>'). "
    "Refs: 'iec:60835-2-1@1990§1' (a clause), '...¶2' (from its 2nd sentence), '60835-2-1' means the newest "
    "imported year; 'IEC CA 01:2020 CSV' and 'ca-01@2020+csv' name a commented version; 'IEC ACEE 01:2018' is "
    "acee-01@2018. iec_outline lists clauses as refs; iec_cite gives the citation. iec_docs lists what is "
    "imported. If a publication is not imported, the error says what to run."
)


def iec_read(ref: str, max_tokens: int = 2000) -> str:
    """Read IEC text by ref, cut at sentence boundaries within max_tokens. A 'next: <ref>' footer line is the ref
    that reads the next page: pass it back as ref.

    ref: 'iec:60835-2-1@1990' | 'iec:60835-2-1@1990§1' | 'iec:60835-2-1@1990§1¶2' | 'IEC ACEE 01:2018'."""
    return library.read(ref, max_tokens=max_tokens)


def iec_search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
    """Find clauses containing the query words (all of them, else any, flagged 'relaxed'), best first. One line per
    hit: '<ref>  <clause title>: <snippet>'. doc restricts to one publication. A 'next: start=N' footer line means
    call again with start=N."""
    return library.search(query, doc=doc, limit=limit, start=start)


def iec_outline(doc: str, start: int = 0, limit: int = 200) -> str:
    """List a publication's clauses, indented by depth, each with the ref that reads it and its PDF page. A
    'next: start=N' footer line means call again with start=N."""
    return library.outline(doc, start=start, limit=limit)


def iec_cite(ref: str) -> str:
    """The citation string for a ref, with the sha256 prefix of the exact text cited (cite: and span: lines)."""
    return library.cite(ref)


def iec_docs() -> str:
    """List the imported IEC publications and whether each source PDF is unchanged, changed or missing."""
    return library.docs()


def _build() -> Any:
    built = MCPServer("primarysource-iec", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, (iec_read, iec_search, iec_outline, iec_cite, iec_docs), annotations=READ_ONLY)
    return built


server = _build()
