"""`primarysource vin ...`: the collection's own commands.

primarysource vin import [FILE]     # no FILE: every PDF in the vin home
primarysource vin index
primarysource vin docs
primarysource vin read <ref> [--max-tokens N]
primarysource vin search <query> [--doc DOC] [--limit N] [--start N]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fsutil import bulk_lock
from primarysource.vin import importer, library


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="primarysource vin", description="General Motors VIN standards filed with NHTSA under 49 CFR Part 565"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="extract and index the filings (default: every PDF in the vin home)")
    imp.add_argument(
        "file", nargs="?", type=Path, help="one PDF; without it, every new or changed PDF in the vin home"
    )
    commands.add_parser("index", help="rebuild the search index from what is imported")
    commands.add_parser("docs", help="what is imported")
    read = commands.add_parser("read", help="read a page by ref")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="find pages containing words")
    search.add_argument("query")
    search.add_argument("--doc")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=0)
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _line(result: importer.ImportResult) -> str:
    line = f"imported vin:{result.doc} ({result.label}): {result.sections} sections ({result.segmenter})"
    return line + (f"\n  note: {result.note}" if result.note else "")


def _import(args: argparse.Namespace, home: Path) -> int:
    with bulk_lock(home, "import"):
        if args.file is not None:
            return _out(_line(importer.import_file(home, args.file)))
        done, skipped = importer.import_folder(home)
    lines = [_line(result) for result in done]
    lines += [f"skipped {name}: {why}" for name, why in skipped]
    if not lines:
        lines = [f"no new or changed PDFs in {home}"]
    return _out("\n".join(lines))


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    home = library.default_home()
    try:
        if args.command == "import":
            return _import(args, home)
        if args.command == "index":
            with bulk_lock(home, "import"):
                return _out(f"indexed {importer.rebuild_index(home)} sections")
        if args.command == "docs":
            return _out(library.docs())
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens))
        return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
