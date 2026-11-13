"""The MCP server and the command line for a pkgdocs collection, built from its `Spec`.

Tools carry the collection's prefix (`gitdocs_read`, `pep_search`), answer in text with the fixed footer, and turn a
`LibError` into an MCP tool error (`isError`) whose text names the remedy. Every tool reads installed files only;
none fetches or writes (`primarysource <collection> import` is the one command that does, and it is not a tool).
`mcp` is imported only when a server is built, so the readers and the importer need nothing but the standard
library.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from primarysource import __version__
from primarysource.errors import LibError
from primarysource.pkgdocs.runtime import Library, Spec
from primarysource.scaffold import add_tools

DEFAULT_MAX_TOKENS = 2000


def build_server(spec: Spec, library: Library | None = None) -> Any:
    """An `MCPServer` with read, outline, search, cite, docs and status tools for `spec`."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    lib = library or Library(spec)
    examples = "; ".join(spec.example_refs)

    def read(ref: str, start: int = 1, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
        return lib.read(ref, start=start, max_tokens=max_tokens)

    def outline(doc: str, start: int = 1, max_tokens: int = 4000) -> str:
        return lib.outline(doc, start=start, max_tokens=max_tokens)

    def search(query: str, doc_prefix: str = "", limit: int = 10, start: int = 1) -> str:
        return lib.search(query, limit=limit, start=start, doc_prefix=doc_prefix)

    def cite(ref: str) -> str:
        return lib.cite(ref)

    def docs(prefix: str = "", limit: int = 200, start: int = 1) -> str:
        return lib.docs(prefix, limit=limit, start=start)

    def status() -> str:
        return lib.status()

    read.__doc__ = (
        f"Read {spec.title} text by ref, cut at block boundaries within max_tokens. A 'next: start=N' footer line "
        "means call again with start=N. The cite: line is the citation.\n\n"
        f"ref: '<doc>[@<commit>]§<section>[#<anchor>][¶<n>]'; the section is an id, an anchor, a heading or a unique "
        f"part of one. Examples: {examples}"
    )
    outline.__doc__ = "List a document's sections, each with the ref that reads it. doc: a document id (see docs)."
    search.__doc__ = (
        f"Find sections of {spec.title} by words (all of them, else some, which the relaxed: line says). "
        "One line per "
        "hit: '<ref>: <document> / <section> -- <snippet>'. doc_prefix narrows to document ids starting with it."
    )
    cite.__doc__ = (
        "The citation for a ref (document, section, edition, commit, source file, licence) and its span hash."
    )
    docs.__doc__ = "List document ids and titles, optionally those whose id starts with prefix."
    status.__doc__ = "What this collection pins, what is imported, and its licence."

    server = MCPServer(f"primarysource-{spec.name}", version=__version__, instructions=spec.instructions)
    annotations = ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False
    )
    add_tools(server, (read, outline, search, cite, docs, status), prefix=spec.prefix, annotations=annotations)
    return server


def _parser(spec: Spec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"primarysource {spec.name}", description=spec.title)
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="fetch the pinned edition (one request per second) and install it")
    imp.add_argument("--tree", help="only this tree")
    imp.add_argument("--commit", help="a pinned edition other than the current one: a label or commit prefix")
    imp.add_argument("--archive", help="read this downloaded archive instead of fetching (needs --tree)")
    imp.add_argument("--allow-unpinned", action="store_true", help="trust the digest of this one fetch")
    commands.add_parser("status", help="what is pinned and imported, and the licence")
    docs = commands.add_parser("docs", help="list documents")
    docs.add_argument("prefix", nargs="?", default="")
    docs.add_argument("--limit", type=int, default=200)
    docs.add_argument("--start", type=int, default=1)
    outline = commands.add_parser("outline", help="a document's sections with their refs")
    outline.add_argument("doc")
    outline.add_argument("--start", type=int, default=1)
    outline.add_argument("--max-tokens", type=int, default=4000)
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    search = commands.add_parser("search", help="find sections by words")
    search.add_argument("query")
    search.add_argument("--doc-prefix", default="")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=1)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _write(text: str) -> None:
    """UTF-8 to stdout whatever the console's code page is: refs contain `§` and `¶`."""
    stream = getattr(sys.stdout, "buffer", None)
    if stream is not None:
        sys.stdout.flush()
        stream.write(text.encode("utf-8"))
        stream.flush()
    else:
        sys.stdout.write(text)


def run(spec: Spec, argv: Sequence[str], library: Library | None = None) -> int:
    """`primarysource <collection> ...`: exit 0, or 1 with the error and its hint on stderr."""
    args = _parser(spec).parse_args(list(argv))
    lib = library or Library(spec)
    try:
        if args.command == "import":
            for report in lib.import_edition(
                args.tree, args.commit, args.archive, allow_unpinned=args.allow_unpinned
            ):
                skipped = ", ".join(f"{k}: {v}" for k, v in sorted(report.skipped.items())) or "none"
                print(
                    f"{report.tree} {report.label} {report.commit[:12]}: {report.docs} documents, {report.sections} "
                    f"sections, {report.units} blocks, {report.warnings} reader warnings\n"
                    f"  files sha256 {report.files_sha256} ({'matches the pin' if report.pinned else 'NOT pinned'})\n"
                    f"  skipped: {skipped}\n  installed at {report.path}"
                )
            return 0
        if args.command == "status":
            text = lib.status()
        elif args.command == "docs":
            text = lib.docs(args.prefix, limit=args.limit, start=args.start)
        elif args.command == "outline":
            text = lib.outline(args.doc, start=args.start, max_tokens=args.max_tokens)
        elif args.command == "read":
            text = lib.read(args.ref, start=args.start, max_tokens=args.max_tokens)
        elif args.command == "search":
            text = lib.search(args.query, limit=args.limit, start=args.start, doc_prefix=args.doc_prefix)
        else:
            text = lib.cite(args.ref)
        _write(text if text.endswith("\n") else text + "\n")
        return 0
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
