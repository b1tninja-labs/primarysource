"""`primarysource c2sp ...`: the collection's own commands.

primarysource c2sp import [--only ID ...]
primarysource c2sp docs
primarysource c2sp outline <doc>
primarysource c2sp read <ref> [--max-tokens N]
primarysource c2sp search <query> [--doc ID] [--limit N] [--start N]
primarysource c2sp cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.c2sp import importer, library
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource c2sp", description="C2SP specifications (CC BY 4.0)")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="fetch and verify the pinned specifications (one request per second)")
    imp.add_argument("--only", action="append", default=[], metavar="ID", help="import only this specification")
    commands.add_parser("docs", help="the catalogue and what is imported")
    commands.add_parser("outline", help="a specification's headings with refs").add_argument("doc")
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="find blocks containing words")
    search.add_argument("query")
    search.add_argument("--doc")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=0)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "import":
            result = importer.import_specs(library.default_home(), args.only)
            return _out(f"imported {len(result.files)} specifications at {result.commit[:7]} into {result.directory}")
        if args.command == "docs":
            return _out(library.docs())
        if args.command == "outline":
            return _out(library.outline(args.doc))
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
        return _out(library.cite(args.ref))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
