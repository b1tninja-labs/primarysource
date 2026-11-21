"""`primarysource iec ...`: free Webstore sync, and the reader's commands.

primarysource iec sync --free [--only ID_OR_REF ...] [--limit N] [--force]
primarysource iec list-free
primarysource iec import [FILE] [--designation "IEC 60835-2-1:1990"]
primarysource iec index
primarysource iec docs
primarysource iec outline <doc>
primarysource iec read <ref>
primarysource iec search <query>
primarysource iec cite <ref>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fsutil import bulk_lock
from primarysource.iec import importer, library, sync


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource iec", description="IEC Webstore free publications")
    commands = parser.add_subparsers(dest="command", required=True)
    sync_cmd = commands.add_parser("sync", help="order and download free publications from the local stubs")
    sync_cmd.add_argument("--free", action="store_true", required=True, help="every free stub (required)")
    sync_cmd.add_argument("--only", action="append", default=[], help="publication id or reference (repeatable)")
    sync_cmd.add_argument("--limit", type=int, default=0, help="stop after N free publications (0 = all)")
    sync_cmd.add_argument("--force", action="store_true", help="re-download even when the PDF is already on disk")
    commands.add_parser("list-free", help="list free stubs under the iec home")
    imp = commands.add_parser("import", help="extract and index IEC PDFs (default: the home and pdfs/)")
    imp.add_argument("file", nargs="?", type=Path, help="one PDF; without it, every new or changed PDF")
    imp.add_argument("--designation", help="as printed, e.g. 'IEC 60835-2-1:1990'")
    commands.add_parser("index", help="rebuild the search index from what is imported")
    commands.add_parser("docs", help="what is imported")
    out = commands.add_parser("outline", help="a publication's clauses with refs")
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
    for sub in commands.choices.values():
        sub.add_argument("--home", type=Path, help="override the iec collection home")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _line(result: importer.ImportResult) -> str:
    line = (
        f"imported iec:{result.doc} ({result.designation}): {result.sections} sections, "
        f"{result.headings_found} headings found ({result.segmenter})"
    )
    return line + (f"\n  note: {result.note}" if result.note else "")


def _import(args: argparse.Namespace, home: Path) -> int:
    with bulk_lock(home, "import"):
        if args.file is not None:
            return _out(_line(importer.import_file(home, args.file, args.designation)))
        if args.designation:
            raise LibError("--designation needs a FILE", "", "primarysource iec import FILE --designation '...'")
        done, skipped = importer.import_folder(home)
    lines = [_line(result) for result in done]
    lines += [f"skipped {name}: {why}" for name, why in skipped]
    if not lines:
        lines = [f"no new or changed PDFs in {home}"]
    return _out("\n".join(lines))


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    home = library.default_home() if getattr(args, "home", None) is None else args.home
    try:
        if args.command == "list-free":
            pubs = sync.free_from_stubs(home / sync.STUBS)
            lines = [f"{p.publication_id}\t{p.head}\t{p.reference}" for p in pubs]
            return _out("\n".join(lines) if lines else f"no free stubs in {home / sync.STUBS}")
        if args.command == "import":
            return _import(args, home)
        if args.command == "index":
            with bulk_lock(home, "import"):
                return _out(f"indexed {importer.rebuild_index(home)} sections")
        if args.command == "docs":
            return _out(library.docs(home=home))
        if args.command == "outline":
            return _out(library.outline(args.doc, start=args.start, limit=args.limit, home=home))
        if args.command == "read":
            return _out(library.read(args.ref, max_tokens=args.max_tokens, home=home))
        if args.command == "search":
            return _out(library.search(args.query, doc=args.doc, limit=args.limit, start=args.start, home=home))
        if args.command == "cite":
            return _out(library.cite(args.ref, home=home))
        results = sync.sync_free(home, only=args.only, limit=args.limit, force=args.force)
        lines = []
        failed = 0
        for result in results:
            if result.note.startswith("error:"):
                flag = "fail"
                failed += 1
            elif result.skipped:
                flag = "skip"
            else:
                flag = "ok"
            lines.append(
                f"{flag}\t{result.publication_id}\t{result.reference}\t{result.bytes}\t{result.path}\t{result.note}"
            )
        if not lines:
            lines = ["no free publications matched"]
        _out("\n".join(lines))
        return 1 if failed else 0
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
