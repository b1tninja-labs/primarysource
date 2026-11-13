"""The MCP server for a fetched-document collection: search, read, outline, info, cite.

Reads local files only. The corpus is loaded on the first call and kept until its `index.json` changes on disk
(a fetch or an OSCAL merge rewrites it), so a running server picks up a new corpus without a restart; `reset()`
drops it outright. Search reads the FTS5 index (`primarysource.pdfcorpus.fts`) read-only.

Tools are registered through `scaffold.add_tools` under their bare names (`search`, `read`, ...): `primarysource mcp`
serves them as `<collection>_<tool>` (`nist_search`), and `primarysource mcp --bare-names` or this module's own
stdio server keeps the bare names the old `nistlib`/`usblib` servers had. Every `LibError` reaches the client as an
`isError` result with `error:`, `hint:` and `action:` lines (PLAN.md §5.10).
"""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource.pdfcorpus import tools
from primarysource.pdfcorpus.corpus import Corpus, load_corpus
from primarysource.pdfcorpus.spec import CorpusSpec
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)


class CorpusServer:
    """One collection's MCP server. `mcp` is the `MCPServer`; the tool functions are attributes, callable directly
    (they raise `LibError`; through `mcp` it becomes an `isError` result)."""

    def __init__(self, spec: CorpusSpec) -> None:
        self.spec = spec
        self._corpus: Corpus | None = None
        self._stamp: tuple[int, int] | None = None
        self.mcp = MCPServer(spec.server_name, instructions=spec.instructions)

        def search(query: str, doc: str | None = None, limit: int = 8, start: int = 0) -> str:
            return tools.search(self._load(), query, doc, limit, start)

        def read(
            doc: str, section: str | None = None, lines: str | None = None, max_tokens: int = tools.READ_TOKENS
        ) -> str:
            return tools.read(self._load(), doc, section, lines, max_tokens)

        def outline(doc: str, start: int = 0, limit: int = tools.OUTLINE_ROWS) -> str:
            return tools.outline(self._load(), doc, start, limit)

        def info(doc: str) -> str:
            return tools.info(self._load(), doc)

        def cite(doc: str, section: str | None = None) -> str:
            return tools.cite(self._load(), doc, section)

        search.__doc__ = _SEARCH
        read.__doc__ = _READ
        outline.__doc__ = _OUTLINE
        info.__doc__ = _INFO
        cite.__doc__ = _CITE.format(example=spec.cite_example)
        self.search, self.read, self.outline, self.info, self.cite = search, read, outline, info, cite
        functions: tuple[Callable[..., str], ...] = (search, read, outline, info, cite)
        add_tools(self.mcp, functions, annotations=READ_ONLY)

    def reset(self) -> None:
        self._corpus = None
        self._stamp = None

    def _load(self) -> Corpus:
        stamp = None
        try:
            stat = (self.spec.corpus_dir() / "index.json").stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
        if self._corpus is None or stamp != self._stamp or self._corpus.root != self.spec.corpus_dir():
            self._corpus = load_corpus(self.spec)
            self._stamp = stamp
        return self._corpus


_SEARCH = """Find sections by keywords (BM25 over the local FTS5 index; a heading match weighs more), best first.

Each hit starts with a ref '<doc_id>§<section>' to pass to read() and cite(), then the heading, line range and a
snippet. doc restricts the search to one document (doc_id or number). Every word is required first; if no section
has them all, sections with some of them are returned and a 'relaxed:' line says so. A 'next: start=N' line means
call again with start=N for more."""
_READ = """Read numbered lines of one section or a line range, cut at whole lines within max_tokens.

doc is a doc_id or number with section='3.2.4' (ids from outline) or lines='120-160', or a ref on its own:
'<doc_id>§3.2.4' or '<doc_id>:120-160'. A 'next:' line holds a ref; pass it back as doc to continue."""
_OUTLINE = """List a document's section tree: ids, headings and line ranges. A 'next: start=N' line means call
again with start=N for the rest."""
_INFO = """Document metadata: number, title, date, status, url, sha256.
A 'warning:' line appears when the status is not 'final'."""
_CITE = """Citation string such as '{example}' plus the document URL.
doc may be a ref ('<doc_id>§<section>'). Headings come verbatim from the index."""
