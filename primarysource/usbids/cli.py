"""`primarysource usbids ...`: the collection's own commands.

primarysource usbids import [--latest] [--sha256 H] [--force]
primarysource usbids sections
primarysource usbids lookup <ref> [--max-tokens N]
primarysource usbids search <text> [--section S] [--limit N] [--start N]
primarysource usbids classify <class> [subclass [protocol]]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.usbids import importer, tools


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource usbids", description="the USB ID database (usb.ids)")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="fetch usb.ids (one request)")
    imp.add_argument("--latest", action="store_true")
    imp.add_argument("--sha256")
    imp.add_argument("--force", action="store_true")
    commands.add_parser("sections", help="the imported snapshot and its counts")
    lookup = commands.add_parser("lookup", help="one entry by ref")
    lookup.add_argument("ref")
    lookup.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="entries by name")
    search.add_argument("text")
    search.add_argument("--section")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--start", type=int, default=0)
    classify = commands.add_parser("classify", help="name a class code triple")
    classify.add_argument("base_class")
    classify.add_argument("subclass", nargs="?")
    classify.add_argument("protocol", nargs="?")
    return parser


def _run(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "import":
            forwarded = [flag for flag, on in (("--latest", args.latest), ("--force", args.force)) if on]
            if args.sha256:
                forwarded += ["--sha256", args.sha256]
            return importer.main(forwarded)
        if args.command == "sections":
            return _run(tools.sections())
        if args.command == "lookup":
            return _run(tools.lookup(args.ref, max_tokens=args.max_tokens))
        if args.command == "search":
            return _run(tools.search(args.text, section=args.section, limit=args.limit, start=args.start))
        return _run(tools.classify(args.base_class, args.subclass, args.protocol))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
