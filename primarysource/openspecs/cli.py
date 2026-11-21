"""`primarysource openspecs ...`: the collection's own commands.

primarysource openspecs fetch
primarysource openspecs sync [--only MS-SMB2]
primarysource openspecs index
primarysource openspecs docs
primarysource openspecs outline <doc>
primarysource openspecs read <ref> [--max-tokens N]
primarysource openspecs search <query> [--doc MS-SMB2] [--limit N] [--start N]
primarysource openspecs cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.openspecs import library, sync


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource openspecs", description="Microsoft Open Specifications")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="walk the Learn tables of contents and write the catalog")
    refreshing = commands.add_parser("sync", help="download catalogued pages and index them")
    refreshing.add_argument("--only", action="append", default=[], help="one specification id (repeatable)")
    commands.add_parser("index", help="rebuild the search index from pages already stored")
    listing = commands.add_parser("docs", help="the catalogued specifications")
    listing.add_argument("--start", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    commands.add_parser("outline", help="one specification's pages").add_argument("doc")
    reading = commands.add_parser("read", help="read one page by ref")
    reading.add_argument("ref")
    reading.add_argument("--max-tokens", type=int, default=2000)
    finding = commands.add_parser("search", help="find pages containing words")
    finding.add_argument("query")
    finding.add_argument("--doc")
    finding.add_argument("--limit", type=int, default=10)
    finding.add_argument("--start", type=int, default=0)
    commands.add_parser("cite", help="the citation for one block").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "fetch":
            fetched = sync.fetch_catalog(library.default_home())
            return _out(
                f"{fetched.documents} documents, {fetched.pages} pages, {fetched.tocs} tables of contents, "
                f"{fetched.missing} missing, {fetched.path}"
            )
        if args.command == "sync":
            rows = sync.sync_pages(library.default_home(), args.only or None)
            lines = [
                f"{'skip' if row.skipped else 'indexed'} {row.doc}: "
                f"{row.sections} sections, {row.requests} request(s)"
                for row in rows
            ]
            return _out("\n".join(lines) if lines else "nothing to index")
        if args.command == "index":
            written = library.build_index()
            return _out(f"{written} sections")
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
        print(exc.as_text(), file=sys.stderr)
        return 2
