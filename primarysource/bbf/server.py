"""MCP server for the bbf collection: `primarysource mcp --collection bbf`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `bbf_` prefix,
answer in text with the fixed footer, and turn a `LibError` into an MCP tool error naming the remedy. Every tool
reads local files only; none writes or fetches.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.bbf import library
from primarysource.errors import LibError

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "Broadband Forum documents from the user's own imports: Technical Reports (TR-069 Amendment 6 Corrigendum 1, "
    "CWMP 1.4) and the TR-181 data-model XML. Loop: bbf_search('<words>') -> bbf_read('<ref>'). Refs: "
    "'bbf:tr-069-1-6-1§3.5' (a report clause as numbered in the PDF; '¶2' is its 2nd sentence) and "
    "'bbf:tr-181-2-22-0-ip§Device.IP.Interface.{i}.Enable' (a data-model node by full path; '¶1' is the 1st "
    "paragraph of its description, BBF {{macros}} left unexpanded). bbf_outline('<doc>') lists clauses or nodes; "
    "bbf_cite('<ref>') gives the citation and the hash of the cited text. If nothing is imported, the error says how."
)


def _guard(fn: Callable[..., str]) -> Callable[..., str]:
    @functools.wraps(fn)  # the SDK reads the tool's schema from the wrapped signature
    def wrapped(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except LibError as exc:
            raise ToolError(exc.as_text()) from None

    return wrapped


def bbf_read(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read Broadband Forum text by ref, cut at unit boundaries within max_tokens. A 'next: start=N' footer line
    means call again with start=N.

    ref: 'tr-069-1-6-1§3.5' (report clause, subsections included) | 'tr-069-1-6-1§3.5¶2' (one sentence) |
      'tr-181-2-22-0-ip§Device.IP.Interface.{i}' (a data-model object: header, contained names, description) |
      '...{i}.Enable¶1' (one description paragraph). 'tr-181-2-22-0-ip' alone gives the file's overview."""
    return library.read(ref, start=start, max_tokens=max_tokens)


def bbf_search(query: str, doc: str | None = None, limit: int = 10, start: int = 1) -> str:
    """Find units containing the query words (all of them, else at least half, flagged 'relaxed'). One line per
    hit: '<ref>: <snippet>'. doc restricts to one document id. A 'next: start=N' footer resumes."""
    return library.search(query, doc=doc, limit=limit, start=start)


def bbf_outline(doc: str, under: str = "", limit: int = 200, start: int = 1) -> str:
    """A report's clauses with refs and pages, or a data model's objects (indented by depth). under: a node path
    to list everything below it, parameters included, e.g. 'Device.IP.Interface.{i}'."""
    return library.outline(doc, under=under, limit=limit, start=start)


def bbf_cite(ref: str) -> str:
    """The citation string for a ref, with the sha256 prefix of the exact text cited (cite: and span: lines)."""
    return library.cite(ref)


def bbf_docs(filter: str = "") -> str:  # noqa: A002 - the tool's argument name
    """List the catalogued reports and data-model files and whether each is imported; filter narrows by id."""
    return library.docs(filter)


def _build() -> Any:
    built = MCPServer("primarysource-bbf", version=__version__, instructions=INSTRUCTIONS)
    for tool in (bbf_read, bbf_search, bbf_outline, bbf_cite, bbf_docs):
        built.add_tool(_guard(tool), name=tool.__name__, annotations=READ_ONLY, structured_output=False)
    return built


server = _build()
