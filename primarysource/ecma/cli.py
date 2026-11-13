"""`primarysource ecma ...`: the collection's own commands.

primarysource ecma import [NUMBER] [--edition N] [--file PDF]
primarysource ecma docs
primarysource ecma outline <doc>
primarysource ecma read <ref> [--start N] [--max-tokens N]
primarysource ecma search <query> [--doc NUMBER] [--limit N] [--start N]
primarysource ecma cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.ecma import importer, library
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource ecma", description="Ecma International standards")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="fetch (or read a file), verify and index one standard")
    imp.add_argument("number", nargs="?", default="427", help="the standard's number (default 427)")
    imp.add_argument("--edition", type=int, help="edition number (default: the newest catalogued)")
    imp.add_argument("--file", type=Path, help="the PDF you downloaded yourself, instead of fetching it")
    commands.add_parser("docs", help="the catalogue and what is imported")
    commands.add_parser("outline", help="a standard's clauses with refs").add_argument("doc")
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="find sentences containing words")
    search.add_argument("query")
    search.add_argument("--doc")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=1)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "import":
            result = importer.import_edition(library.default_home(), args.number, args.edition, file=args.file)
            return _out(
                f"imported {result.key}: {result.sections} sections, {result.requests} request(s), {result.pdf}"
            )
        if args.command == "docs":
            return _out(library.docs())
        if args.command == "outline":
            return _out(library.outline(args.doc))
        if args.command == "read":
            return _out(library.read(args.ref, start=args.start, max_tokens=args.max_tokens))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
        return _out(library.cite(args.ref))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
