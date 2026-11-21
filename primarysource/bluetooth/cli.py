"""`primarysource bluetooth ...`.

primarysource bluetooth fetch
primarysource bluetooth sync [--only battery-service]
primarysource bluetooth index
primarysource bluetooth docs
primarysource bluetooth outline <doc>
primarysource bluetooth read <ref>
primarysource bluetooth search <query>
primarysource bluetooth cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.bluetooth import library, sync
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource bluetooth", description="Bluetooth specifications")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="download the specifications catalog")
    refreshing = commands.add_parser("sync", help="download catalogued HTML books and index them")
    refreshing.add_argument("--only", action="append", default=[], help="one specification slug (repeatable)")
    commands.add_parser("index", help="rebuild the search index from books already stored")
    listing = commands.add_parser("docs", help="the catalog")
    listing.add_argument("--start", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    commands.add_parser("outline", help="one specification's sections").add_argument("doc")
    reading = commands.add_parser("read", help="read a specification by ref")
    reading.add_argument("ref")
    reading.add_argument("--max-tokens", type=int, default=2000)
    finding = commands.add_parser("search", help="find sections containing words")
    finding.add_argument("query")
    finding.add_argument("--doc")
    finding.add_argument("--limit", type=int, default=10)
    finding.add_argument("--start", type=int, default=0)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "fetch":
            specs = sync.fetch_catalog(library.default_home())
            return _out(f"{len(specs)} specifications")
        if args.command == "sync":
            rows = sync.sync_books(library.default_home(), args.only)
            library.build_index()
            lines = [
                f"{'skip' if row.skipped else 'ok'}	{row.doc}	{row.sections}	{row.note}".rstrip()
                for row in rows
            ]
            return _out("\n".join(lines) if lines else "nothing to import")
        if args.command == "index":
            return _out(f"{library.build_index()} sections")
        if args.command == "docs":
            return _out(library.docs(start=args.start, limit=args.limit))
        if args.command == "outline":
            return _out(library.outline(args.doc))
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
        return _out(library.cite(args.ref))
    except LibError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"hint: {exc.hint}", file=sys.stderr)
        if exc.action:
            print(f"action: {exc.action}", file=sys.stderr)
        return 1
