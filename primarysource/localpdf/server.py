"""MCP server of a local-PDF collection, built from its spec: `primarysource mcp --collection <name>`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the collection's prefix,
answer in text with the fixed footer, and turn a `LibError` into an MCP tool error with `error:`/`hint:`/`action:`
lines. Every tool reads local files only; none writes or fetches, and every one passes the terms gate
(`localpdf.library`): with the owner's variable unset each refuses and says why. Serve it on the owner's own
machine (stdio, or a container with the home mounted read-only): the PDFs behind it are not ours to distribute.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.localpdf import library
from primarysource.localpdf.spec import LocalPdfSpec
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)


def _named(fn: Callable[..., str], name: str, doc: str) -> Callable[..., str]:
    fn.__name__ = fn.__qualname__ = name
    fn.__doc__ = doc
    return fn


def tools(spec: LocalPdfSpec) -> list[Callable[..., str]]:
    """The five tools of `spec`, named `<prefix>read`, `search`, `outline`, `cite` and `docs`."""
    p, unit = spec.prefix, spec.unit.value

    def read(ref: str, max_tokens: int = 2000) -> str:
        return library.read(spec, ref, max_tokens=max_tokens)

    def search(query: str, doc: str | None = None, limit: int = 10, start: int = 0) -> str:
        return library.search(spec, query, doc=doc, limit=limit, start=start)

    def outline(doc: str, start: int = 0, limit: int = 200) -> str:
        return library.outline(spec, doc, start=start, limit=limit)

    def cite(ref: str) -> str:
        return library.cite(spec, ref)

    def docs() -> str:
        return library.docs(spec)

    return [
        _named(
            read,
            f"{p}read",
            f"Read {spec.title} text by ref, cut at {unit} boundaries within max_tokens. A 'next: <ref>' footer line "
            "is the ref that reads the next page: pass it back as ref.\n\n"
            f"ref: '{spec.name}:<doc>' (whole document) | '{spec.ref_example}' (a section) | "
            f"'...¶3' (from its 3rd {unit}). {p}cite gives exactly one {unit}.",
        ),
        _named(
            search,
            f"{p}search",
            "Find sections containing the query words (all of them, else any, flagged 'relaxed'), best first. One "
            "line per hit: '<ref>  <section title>: <snippet>'. doc restricts to one document id. A 'next: start=N' "
            "footer line means call again with start=N (a 0-based offset).",
        ),
        _named(
            outline,
            f"{p}outline",
            "List a document's sections, indented by depth, each with the ref that reads it and its PDF page. A "
            "'next: start=N' footer line means call again with start=N.",
        ),
        _named(
            cite,
            f"{p}cite",
            "The citation string for a ref, with the sha256 prefix of the exact text cited (cite: and span: lines).",
        ),
        _named(
            docs,
            f"{p}docs",
            f"List the imported {spec.title} documents, whether each source PDF is unchanged, changed or missing, "
            "and when the owner's terms acknowledgement was recorded for each.",
        ),
    ]


def build_server(spec: LocalPdfSpec) -> Any:
    """The `MCPServer` for `spec`."""
    built = MCPServer(f"primarysource-{spec.name}", version=__version__, instructions=spec.instructions)
    add_tools(built, tools(spec), prefix=spec.prefix, annotations=READ_ONLY)
    return built
