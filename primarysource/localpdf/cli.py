"""`primarysource <name> ...`: the commands of a local-PDF collection, built from its spec.

primarysource <name> import [PATH]     # a PDF, or a folder of them; no PATH: every PDF in the home
primarysource <name> index
primarysource <name> docs
primarysource <name> outline <doc> [--start N] [--limit N]
primarysource <name> read <ref> [--max-tokens N]
primarysource <name> search <query> [--doc DOC] [--limit N] [--start N]
primarysource <name> cite <ref>

Each command passes the gate first: with the collection's terms variable unset, a command refuses and says why
(`terms.py`). The import checks it before the home folder or its lock is created.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from primarysource import terms
from primarysource.errors import LibError
from primarysource.fsutil import bulk_lock
from primarysource.localpdf import library, store
from primarysource.localpdf.spec import LocalPdfSpec


def _parser(spec: LocalPdfSpec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"primarysource {spec.name}", description=spec.title)
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="extract and index your PDFs (default: every PDF in the home)")
    imp.add_argument("path", nargs="?", type=Path, help="one PDF, or a folder of them; without it, the home folder")
    commands.add_parser("index", help="rebuild the search index from what is imported")
    commands.add_parser("docs", help="what is imported")
    out = commands.add_parser("outline", help="a document's sections with refs")
    out.add_argument("doc")
    out.add_argument("--start", type=int, default=0)
    out.add_argument("--limit", type=int, default=200)
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="find sections containing words")
    search.add_argument("query")
    search.add_argument("--doc")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--start", type=int, default=0)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def _line(spec: LocalPdfSpec, result: store.ImportResult) -> str:
    line = (
        f"imported {spec.name}:{result.doc} ({result.label}): {result.sections} sections from "
        f"{result.pages} pages ({result.segmenter})"
    )
    return line + (f"\n  warning: {result.empty_pages} pages have no text layer" if result.empty_pages else "")


def _import(spec: LocalPdfSpec, args: argparse.Namespace, home: Path) -> int:
    terms.require_accepted(spec.terms, home, f"the {spec.name} import")  # before the home or its lock exists
    path: Path | None = args.path
    with bulk_lock(home, "import"):
        if path is not None and path.is_file():
            return _out(_line(spec, store.import_file(spec, home, path)))
        done, skipped = store.import_folder(spec, home, path)
    lines = [_line(spec, r) for r in done]
    lines += [f"skipped {name}: {why}" for name, why in skipped]
    return _out("\n".join(lines) or f"no PDFs in {path or home}")


def make_main(spec: LocalPdfSpec) -> Callable[[Sequence[str]], int]:
    """The `main(argv)` of the collection's command line."""

    def main(argv: Sequence[str]) -> int:
        args = _parser(spec).parse_args(list(argv))
        home = library.default_home(spec)
        try:
            if args.command == "import":
                return _import(spec, args, home)
            if args.command == "index":
                terms.require_accepted(spec.terms, home, f"the {spec.name} index")
                with bulk_lock(home, "import"):
                    return _out(f"indexed {store.rebuild_index(spec, home)} sections")
            if args.command == "docs":
                return _out(library.docs(spec))
            if args.command == "outline":
                return _out(library.outline(spec, args.doc, start=args.start, limit=args.limit))
            if args.command == "read":
                return _out(library.read(spec, args.ref, max_tokens=args.max_tokens))
            if args.command == "search":
                return _out(library.search(spec, args.query, doc=args.doc, limit=args.limit, start=args.start))
            return _out(library.cite(spec, args.ref))
        except LibError as exc:
            print(exc.as_text(), file=sys.stderr)
            return 1

    return main
