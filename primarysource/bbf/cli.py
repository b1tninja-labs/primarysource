"""`primarysource bbf ...`: the collection's own commands.

primarysource bbf import-models [ID ...]
primarysource bbf import-report <ID> [--file PDF]
primarysource bbf docs [FILTER]
primarysource bbf outline <doc> [--under PATH] [--limit N] [--start N]
primarysource bbf read <ref> [--max-tokens N]
primarysource bbf search <query> [--doc ID] [--limit N] [--start N]
primarysource bbf cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.bbf import importer, library
from primarysource.errors import LibError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource bbf", description="Broadband Forum data models and reports")
    commands = parser.add_subparsers(dest="command", required=True)
    models = commands.add_parser("import-models", help="fetch and verify data-model XML (one request per second)")
    models.add_argument("ids", nargs="*", help="file stems to import (default: every catalogued file)")
    report = commands.add_parser(
        "import-report", help="fetch (or read a file), verify and extract a Technical Report"
    )
    report.add_argument("id", help="e.g. tr-069-1-6-1")
    report.add_argument("--file", type=Path, help="the PDF you downloaded yourself, instead of fetching it")
    commands.add_parser("docs", help="the catalogue and what is imported").add_argument(
        "filter", nargs="?", default=""
    )
    outline = commands.add_parser("outline", help="clauses of a report, or nodes of a data model")
    outline.add_argument("doc")
    outline.add_argument("--under", default="")
    outline.add_argument("--limit", type=int, default=200)
    outline.add_argument("--start", type=int, default=0)
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="find units containing words")
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
        if args.command == "import-models":
            result = importer.import_models(home, args.ids)
            return _out(f"imported {len(result.ids)} data-model files, {result.requests} request(s), into {home}")
        if args.command == "import-report":
            result = importer.import_report(home, args.id, file=args.file)
            return _out(f"imported {args.id}, {result.requests} request(s), into {home}")
        if args.command == "docs":
            return _out(library.docs(args.filter))
        if args.command == "outline":
            return _out(library.outline(args.doc, under=args.under, limit=args.limit, start=args.start))
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start))
        return _out(library.cite(args.ref))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
