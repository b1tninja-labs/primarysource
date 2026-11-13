"""MCP server (stdio) exposing the local USB-IF corpus: search, read, outline, info, cite.

Built on the same ``mcp`` SDK ``MCPServer`` as rfclib. Reads local files only.
"""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as McpToolError
from mcp.types import ToolAnnotations

from . import tools
from .corpus import Corpus, CorpusError, load_corpus

INSTRUCTIONS = (
    "USB-IF specifications from a locally fetched corpus. "
    "search('<question>') -> read(doc, section=<id>) -> cite(doc, section=<id>). "
    "Documents are addressed by doc_id or by number. Check info(doc) for status before quoting. "
    "If the corpus is missing, tools say so and name `usblib-fetch`."
)
RO = ToolAnnotations(
    read_only_hint=True,
    idempotent_hint=True,
    destructive_hint=False,
    open_world_hint=False,
)

mcp = MCPServer("usblib", instructions=INSTRUCTIONS)

_corpus: Corpus | None = None


def _load() -> Corpus:
    global _corpus
    if _corpus is None:
        _corpus = load_corpus()
    return _corpus


def _run(fn: Callable[..., str], *args: object) -> str:
    try:
        return fn(_load(), *args)
    except (CorpusError, tools.ToolError) as e:
        raise McpToolError(str(e)) from None


@mcp.tool(annotations=RO, structured_output=False)
def search(query: str, doc: str | None = None, limit: int = 8) -> str:
    """Find passages across the corpus by plain token matching, best first.

    Each hit gives doc_id, section id, heading and a short snippet with line numbers,
    ready for read() and cite(). doc restricts the search to one document (doc_id or number).
    """
    return _run(tools.search, query, doc, limit)


@mcp.tool(annotations=RO, structured_output=False)
def read(doc: str, section: str | None = None, lines: str | None = None) -> str:
    """Return the text of one section (section='3.2.4', ids from outline) or a line range
    (lines='120-160'), with line numbers. Give exactly one of section or lines."""
    return _run(tools.read, doc, section, lines)


@mcp.tool(annotations=RO, structured_output=False)
def outline(doc: str) -> str:
    """List a document's section tree: ids, headings and line ranges."""
    return _run(tools.outline, doc)


@mcp.tool(annotations=RO, structured_output=False)
def info(doc: str) -> str:
    """Document metadata: number, title, date, status, url, sha256.
    Warns when the status is not 'final'."""
    return _run(tools.info, doc)


@mcp.tool(annotations=RO, structured_output=False)
def cite(doc: str, section: str | None = None) -> str:
    """Citation string such as 'USB-IF CCID Rev 1.1 §6.1.1' plus the document URL.
    Headings come verbatim from the index."""
    return _run(tools.cite, doc, section)


def main() -> None:
    """``usblib-mcp`` entry point: serve over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
