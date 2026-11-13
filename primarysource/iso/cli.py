"""`primarysource iso ...`: the collection's own commands.

primarysource iso import [FILE] [--designation "ISO/IEC 9899:2024"]   # no FILE: every PDF in purchased/
primarysource iso index
primarysource iso docs
primarysource iso outline <doc> [--start N] [--limit N]
primarysource iso read <ref> [--max-tokens N]
primarysource iso search <query> [--doc DOC] [--limit N] [--start N]
primarysource iso cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fsutil import bulk_lock
from primarysource.iso import importer, library


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource iso", description="ISO standards from your own PDFs")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="extract and index your PDFs (default: every PDF in purchased/)")
    imp.add_argument("file", nargs="?", type=Path, help="one PDF; without it, every new or changed PDF in purchased/")
    imp.add_argument("--designation", help="as printed on the cover, e.g. 'ISO/IEC 9899:2024'")
    commands.add_parser("index", help="rebuild the search index from what is imported")
    commands.add_parser("docs", help="what is imported")
    out = commands.add_parser("outline", help="a standard's clauses with refs")
    out.add_argument("doc")
    out.add_argument("--start", type=int, default=0)
    out.add_argument("--limit", type=int, default=200)
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="find clauses containing words")
    search.add_argument("query")
    search.add_argument("--doc")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=0)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _import(args: argparse.Namespace, home: Path) -> int:
    with bulk_lock(home, "import"):
        if args.file is not None:
            result = importer.import_file(home, args.file, args.designation)
            return _out(
                f"imported iso:{result.doc} ({result.designation}): {result.sections} sections, "
                f"{result.headings_found} headings found in the text"
            )
        if args.designation:
            raise LibError("--designation needs a FILE", "", "primarysource iso import FILE --designation '...'")
        (home / importer.PURCHASED).mkdir(parents=True, exist_ok=True)
        done, skipped = importer.import_folder(home)
    lines = [f"imported iso:{r.doc} ({r.designation}): {r.sections} sections" for r in done]
    lines += [f"skipped {name}: {why}" for name, why in skipped]
    if not lines:
        lines = [f"no PDFs in {home / importer.PURCHASED}"]
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
        if args.command == "outline":
            return _out(library.outline(args.doc, start=args.start, limit=args.limit))
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
        return _out(library.cite(args.ref))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
