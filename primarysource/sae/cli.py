"""`primarysource sae import FILE [--designation "SAE J2534:2002"]` and the read commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fsutil import bulk_lock
from primarysource.sae import importer, library


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource sae")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="extract and index one PDF; the PDF is not copied")
    imp.add_argument("file", type=Path)
    imp.add_argument("--designation", help='as printed on the cover, e.g. "SAE J2534:2002"')
    commands.add_parser("index")
    commands.add_parser("docs")
    out = commands.add_parser("outline")
    out.add_argument("doc")
    out.add_argument("--start", type=int, default=0)
    out.add_argument("--limit", type=int, default=200)
    read = commands.add_parser("read")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--doc")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=0)
    commands.add_parser("cite").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    home = library.default_home()
    try:
        if args.command == "import":
            with bulk_lock(home, "import"):
                result = importer.import_file(home, args.file, args.designation)
            return _out(
                f"imported sae:{result.doc} ({result.designation}): {result.sections} sections ({result.segmenter})"
            )
        if args.command == "index":
            with bulk_lock(home, "import"):
                return _out(f"indexed {importer.rebuild_index(home)} sections")
        if args.command == "docs":
            return _out(library.docs())
        if args.command == "outline":
            return _out(library.outline(args.doc, start=args.start, limit=args.limit))
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
        if args.command == "cite":
            return _out(library.cite(args.ref))
    except LibError as exc:
        print(exc.message, file=sys.stderr)
        if exc.action:
            print(exc.action, file=sys.stderr)
        return 1
    return 2
