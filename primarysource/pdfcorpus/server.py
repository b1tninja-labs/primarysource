"""The MCP server for a fetched-document collection: search, read, outline, info, cite.

Reads local files only. The corpus is loaded on the first call and kept; `reset()` drops it so the next call
reads the index again (after a fetch, or in a test).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource.errors import LibError
from primarysource.pdfcorpus import tools
from primarysource.pdfcorpus.corpus import Corpus, CorpusError, load_corpus
from primarysource.pdfcorpus.spec import CorpusSpec
from primarysource.scaffold import tool_error

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)


class CorpusServer:
    """One collection's MCP server. `mcp` is the `MCPServer`; the tool methods are callable directly."""

    def __init__(self, spec: CorpusSpec) -> None:
        self.spec = spec
        self._corpus: Corpus | None = None
        self.mcp = MCPServer(spec.server_name, instructions=spec.instructions)
        tool = self.mcp.tool
        tool(annotations=READ_ONLY, structured_output=False, name="search", description=_SEARCH)(self.search)
        tool(annotations=READ_ONLY, structured_output=False, name="read", description=_READ)(self.read)
        tool(annotations=READ_ONLY, structured_output=False, name="outline", description=_OUTLINE)(self.outline)
        tool(annotations=READ_ONLY, structured_output=False, name="info", description=_INFO)(self.info)
        cite = _CITE.format(example=spec.cite_example)
        tool(annotations=READ_ONLY, structured_output=False, name="cite", description=cite)(self.cite)

    def reset(self) -> None:
        self._corpus = None

    def _load(self) -> Corpus:
        if self._corpus is None:
            self._corpus = load_corpus(self.spec)
        return self._corpus

    def _run(self, fn: Callable[..., str], *args: Any) -> str:
        try:
            return fn(self._load(), *args)
        except (CorpusError, tools.ToolError) as e:
            # the remedy is written into the message, so there is no hint: line to split out yet
            raise tool_error(LibError(str(e))) from None

    def search(self, query: str, doc: str | None = None, limit: int = 8) -> str:
        return self._run(tools.search, query, doc, limit)

    def read(self, doc: str, section: str | None = None, lines: str | None = None) -> str:
        return self._run(tools.read, doc, section, lines)

    def outline(self, doc: str) -> str:
        return self._run(tools.outline, doc)

    def info(self, doc: str) -> str:
        return self._run(tools.info, doc)

    def cite(self, doc: str, section: str | None = None) -> str:
        return self._run(tools.cite, doc, section)


_SEARCH = """Find passages across the corpus by plain token matching, best first.

Each hit gives doc_id, section id, heading and a short snippet with line numbers,
ready for read() and cite(). doc restricts the search to one document (doc_id or number)."""
_READ = """Return the text of one section (section='3.2.4', ids from outline) or a line range
(lines='120-160'), with line numbers. Give exactly one of section or lines."""
_OUTLINE = "List a document's section tree: ids, headings and line ranges."
_INFO = """Document metadata: number, title, date, status, url, sha256.
Warns when the status is not 'final'."""
_CITE = """Citation string such as '{example}' plus the document URL.
Headings come verbatim from the index."""
