"""`primarysource msos ...`: download the Open Specifications zips and read them.

primarysource msos sync [--only SET]
primarysource msos import [--only SET_OR_DOC]
primarysource msos docs
primarysource msos outline <doc>
primarysource msos read <ref>
primarysource msos search <query>
primarysource msos cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.fsutil import bulk_lock
from primarysource.msos import importer, library, sync


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource msos", description="Microsoft Open Specifications")
    commands = parser.add_subparsers(dest="command", required=True)
    downloaded = commands.add_parser("sync", help="download the PDF zips linked from the Open Specifications pages")
    downloaded.add_argument("--only", action="append", default=[], help="one set id, e.g. exchange (repeatable)")
    imp = commands.add_parser("import", help="index the PDFs in the downloaded zips")
    imp.add_argument("--only", action="append", default=[], help="a set id or a specification id")
    commands.add_parser("index", help="rebuild the search index")
    commands.add_parser("docs", help="what is imported")
    out = commands.add_parser("outline", help="a specification's clauses")
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


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    home = library.default_home()
    try:
        if args.command == "sync":
            results = sync.sync_sets(home, args.only)
            lines = [
                f"{'skip' if item.skipped else 'ok'}\t{item.set_id}\t{item.size}\t{item.path}" for item in results
            ]
            return _out("\n".join(lines) if lines else "no sets matched")
        if args.command == "import":
            with bulk_lock(home, "import"):
                done, skipped = importer.import_zips(home, args.only)
            lines = [
                f"imported msos:{item.doc} ({item.designation}): {item.sections} sections ({item.segmenter})"
                + (f"\n  note: {item.note}" if item.note else "")
                for item in done
            ]
            lines += [f"skipped {name}: {why}" for name, why in skipped]
            return _out("\n".join(lines) if lines else "no new or changed specifications")
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
