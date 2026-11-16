"""The `primarysource` command.

    primarysource collections                       list what is registered
    primarysource identify <pdf or folder> ...      which collection knows each PDF, and how to import it
    primarysource mcp --collection rfc [--collection nist ...] [--bare-names]
                      [--transport http] [--host H] [--port P] [--allowed-host H] [--read-only]
    primarysource rfc <command> ...                 the collection's own commands (sync, index, status, ...)

`mcp` serves every named collection from one process, each with its own database and its tools named
`<collection>_<tool>` (PLAN.md §5.12). `--bare-names` keeps a collection's own tool names instead; it is how the
old single-collection commands (`rfclib mcp`) stay compatible, and two collections with the same bare names are
refused at startup.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from primarysource import registry, scaffold, serve
from primarysource.envfile import load_env
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource", description="Search, read and cite primary sources.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collections", help="list the registered collections")
    ident = commands.add_parser("identify", help="say which collection knows each PDF, and how to import it")
    ident.add_argument("paths", nargs="+", type=Path, help="PDFs, or folders of PDFs")
    mcp = commands.add_parser("mcp", help="run the MCP server for one or more collections")
    mcp.add_argument(
        "--collection", action="append", required=True, help="a collection to serve, e.g. rfc (repeatable)"
    )
    mcp.add_argument(
        "--bare-names",
        action="store_true",
        help="keep each collection's own tool names (search, read) instead of <collection>_<tool>",
    )
    mcp.add_argument("--transport", default="stdio", help="stdio (one server per client) or http (one shared server)")
    mcp.add_argument("--host", default="127.0.0.1", help="http: address to bind; there is no authentication")
    mcp.add_argument("--port", type=int, default=serve.MCP_HTTP_PORT, help="http: TCP port")
    mcp.add_argument("--allowed-host", action="append", default=[], help="http: Host header to accept (repeatable)")
    mcp.add_argument("--read-only", action="store_true", help="never write the library and never fetch")
    return parser


def collection_server(collection: registry.Collection) -> Any:
    """The `MCPServer` a collection's own module builds; a factory such as itu's `build()` is called."""
    server = registry.attribute(collection, collection.server, "server")
    if not hasattr(server, "run") and callable(server):
        server = server()
    return server


def build_server(names: Sequence[str], *, bare: bool = False) -> Any:
    """The one server for `names`, in the order given; a name given twice is served once."""
    served = []
    for name in dict.fromkeys(names):
        collection = registry.load(name)
        served.append(scaffold.Served(collection.name, collection.title, collection_server(collection)))
    return scaffold.compose(served, bare=bare)


def main(argv: Sequence[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    try:
        # A stdio client often starts this process without the user-account environment. The checkout `.env`
        # supplies PRIMARYSOURCE_HOME and the webstore accounts; a variable the client already set is kept.
        load_env()
        # `primarysource <collection> ...` hands the rest of the line to that collection's own command
        if args_in and args_in[0] in registry.available():
            collection = registry.load(args_in[0])
            entry = registry.attribute(collection, collection.cli, "command line")
            result = entry(args_in[1:])
            return int(result or 0)
        args = _parser().parse_args(args_in)
        if args.command == "collections":
            for name in registry.available():
                print(name)
            return 0
        if args.command == "identify":
            from primarysource import identify

            hooks = identify.registered_hooks()
            for path in identify.pdfs(args.paths):
                try:
                    print(identify.describe(path, identify.identify(identify.probe_pdf(path), hooks)))
                except LibError as exc:
                    print(f"{path.name}: {exc.message}")
            return 0
        transport = serve.normalise_transport(args.transport)
        if args.read_only:
            os.environ["PRIMARYSOURCE_READONLY"] = "1"
        server = build_server(args.collection, bare=args.bare_names)
        if transport == "http":
            names = ", ".join(dict.fromkeys(args.collection))
            print(f"primarysource mcp: {names} at http://{args.host}:{args.port}/mcp", file=sys.stderr)
        serve.run(server, transport, host=args.host, port=args.port, allowed_hosts=args.allowed_host)
        return 0
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
