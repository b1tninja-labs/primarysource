"""`primarysource iana ...`: the collection's own commands.

primarysource iana list
primarysource iana import <name>... | --all [--force] [--interval SECONDS]
primarysource iana read <ref> [--start N] [--max-tokens N]
primarysource iana lookup <registry-ref> <value>
primarysource iana search <text> [--file NAME] [--limit N] [--start N]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.iana import importer, reader


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource iana", description="IANA protocol registries")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="the catalogue, marked imported or not")
    imp = commands.add_parser("import", help="fetch registry XML from iana.org (at most 1 request per second)")
    imp.add_argument("names", nargs="*", help="registry file names, e.g. dns-parameters")
    imp.add_argument("--all", action="store_true", help="every registry in the catalogue")
    imp.add_argument("--force", action="store_true", help="fetch even if the server says nothing changed")
    imp.add_argument("--interval", type=float, default=importer.MIN_INTERVAL, help="seconds between requests (>= 1)")
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--max-tokens", type=int, default=2000)
    look = commands.add_parser("lookup", help="the record(s) with a value")
    look.add_argument("registry")
    look.add_argument("value")
    find = commands.add_parser("search", help="find records containing every word")
    find.add_argument("text")
    find.add_argument("--file")
    find.add_argument("--limit", type=int, default=20)
    find.add_argument("--start", type=int, default=1)
    return parser


def _out(text: str) -> int:
    # UTF-8 bytes: registry text has names a Windows console code page cannot encode
    sys.stdout.flush()
    sys.stdout.buffer.write((text if text.endswith("\n") else text + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "list":
            return _out(reader.listing())
        if args.command == "import":
            names = importer.catalogue_names() if args.all else args.names
            report = importer.import_registries(names, force=args.force, interval=args.interval)
            for o in report.outcomes:
                print(f"{o.name}: {o.status}, updated {o.updated or '-'}, {o.size:,} bytes, sha256 {o.sha256[:16]}")
            return 0
        if args.command == "read":
            return _out(reader.read(args.ref, start=args.start, max_tokens=args.max_tokens))
        if args.command == "lookup":
            return _out(reader.lookup(args.registry, args.value))
        return _out(reader.search(args.text, file=args.file, limit=args.limit, start=args.start))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
