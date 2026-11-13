"""The `primarysource` command.

    primarysource collections                       list what is registered
    primarysource mcp --collection rfc [--transport http] [--host H] [--port P] [--allowed-host H] [--read-only]
    primarysource rfc <command> ...                 the collection's own commands (sync, index, status, ...)

One collection per server today; serving several from one process is `cl.multi_collection_server`.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from primarysource import registry, serve
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource", description="Search, read and cite primary sources.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collections", help="list the registered collections")
    mcp = commands.add_parser("mcp", help="run the MCP server for a collection")
    mcp.add_argument("--collection", required=True, help="the collection to serve, e.g. rfc")
    mcp.add_argument("--transport", default="stdio", help="stdio (one server per client) or http (one shared server)")
    mcp.add_argument("--host", default="127.0.0.1", help="http: address to bind; there is no authentication")
    mcp.add_argument("--port", type=int, default=serve.MCP_HTTP_PORT, help="http: TCP port")
    mcp.add_argument("--allowed-host", action="append", default=[], help="http: Host header to accept (repeatable)")
    mcp.add_argument("--read-only", action="store_true", help="never write the library and never fetch")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_in = list(sys.argv[1:] if argv is None else argv)
    try:
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
        collection = registry.load(args.collection)
        transport = serve.normalise_transport(args.transport)
        if args.read_only:
            os.environ["PRIMARYSOURCE_READONLY"] = "1"
        server = registry.attribute(collection, collection.server, "server")
        if transport == "http":
            print(f"primarysource mcp: {collection.name} at http://{args.host}:{args.port}/mcp", file=sys.stderr)
        serve.run(server, transport, host=args.host, port=args.port, allowed_hosts=args.allowed_host)
        return 0
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
