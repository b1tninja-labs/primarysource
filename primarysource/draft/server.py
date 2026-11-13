"""The MCP server for the draft collection: `primarysource mcp --collection draft`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `draft_` prefix,
answer in text with the fixed footer, and turn a `LibError` into an MCP tool error (`isError`) whose text names
the remedy. Every tool reads local files only: none writes, none fetches. Drafts arrive by
`primarysource draft import`, which is a command a person runs, not a tool an agent calls.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.draft import views
from primarysource.draft.store import Store
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "IETF Internet-Drafts from the user's own imported copies: documents that exist only as drafts (RTR version 2 "
    "and the ASPA PDU, ASPA verification, LibrePGP, the TURN REST API). A draft is not a standard: it has "
    "revisions, expires six months after its last one, and is replaced or becomes an RFC. Every result names the "
    "revision it read and, when the draft is dead (expired, replaced, withdrawn, published as an RFC) or the "
    "revision is not the latest, says so in a banner line and in the warning: footer. Never quote or cite a "
    "draft without reading that. Cite only as 'Work in Progress' with the cite: line. Loop: draft_list -> "
    "draft_info('<name>') -> draft_search('<words>') or draft_outline('<name>') -> draft_read('<ref>') -> "
    "draft_cite('<ref>'). Refs: 'draft-ietf-sidrops-8210bis-17§5.1¶2'; without the -17 the latest stored revision "
    "is read and the result says so. If a draft is not stored, the error says which command imports it."
)


def _library() -> Store:
    return Store()


def draft_read(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read a stored Internet-Draft by ref, cut at paragraph boundaries within max_tokens. A 'next: start=N'
    footer line means call again with start=N. Read the banner and warning: lines first: they say if the draft is
    expired, replaced, withdrawn or an RFC now, and if the revision is not the latest.

    ref: 'draft-ietf-sidrops-8210bis-17' (abstract and outline) | '...-17§5.1' (a section) | '...-17§5.1¶2' (one
      paragraph) | '...-17:100-120' (lines of the text) | without '-17' the latest stored revision, said so.
      Sections are numbered as the draft prints them; 'A.1' is Appendix A.1; unnumbered ones are 'abstract',
      'security-considerations'."""
    return views.read(_library(), ref, start=start, max_tokens=max_tokens)


def draft_outline(name: str) -> str:
    """List a stored draft's sections, each as the ref that reads it with its paragraph count. name:
    'draft-ietf-sidrops-8210bis' or '...-17'."""
    return views.outline(_library(), name)


def draft_search(query: str, name: str | None = None, limit: int = 10) -> str:
    """Search the sections of the stored drafts (each draft's latest stored revision) by words, best first. One
    line per hit: '<ref>  <section>: <snippet>', with [expired], [replaced] and so on after hits in a draft that
    is not alive. name: restrict to one draft or one revision. limit: 1 to 50."""
    return views.search(_library(), query, limit=limit, name=name)


def draft_cite(ref: str) -> str:
    """The citation for a draft ref: authors, title, 'Work in Progress, Internet-Draft', name-revision, date, URL
    and section, with a span: hash of the cited text. Drafts may be cited only as work in progress (RFC 2026
    §2.2); the warning: line says if this one is dead."""
    return views.cite(_library(), ref)


def draft_info(name: str) -> str:
    """Standing of a draft: datatracker state, latest revision, expiry, what replaced it, whether it became an
    RFC, revisions stored, licence legend and pins. Call this before relying on a draft."""
    return views.info(_library(), name)


def draft_list() -> str:
    """List the tracked and stored drafts with stored revisions, latest known revision, state and replacement."""
    return views.list_tracked(_library())


def _build() -> Any:
    tools: list[Callable[..., str]] = [draft_read, draft_outline, draft_search, draft_cite, draft_info, draft_list]
    built = MCPServer("primarysource-draft", version=__version__, instructions=INSTRUCTIONS)
    add_tools(built, tools, annotations=READ_ONLY)
    return built


server = _build()
