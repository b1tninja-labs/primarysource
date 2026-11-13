"""`primarysource posix ...` and `primarysource ieee802 ...`: the collections' own commands.

primarysource posix import <susv5.tgz>
primarysource posix pages [volume]
primarysource posix outline <page>
primarysource posix read <ref> [--start N] [--max-tokens N]
primarysource posix grep <text> [--volume V] [--limit N] [--start N]
primarysource ieee802 import <file.pdf> <designation>
primarysource ieee802 outline <designation>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.ieee import ieee802, importer, posix


def _posix_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource posix", description="IEEE Std 1003.1-2024 (POSIX)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import", help="verify and import the user's susv5.tgz").add_argument("archive")
    commands.add_parser("pages", help="list page ids").add_argument("volume", nargs="?")
    commands.add_parser("outline", help="a page's headings with refs").add_argument("page")
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--max-tokens", type=int, default=2000)
    grep = commands.add_parser("grep", help="find blocks containing text")
    grep.add_argument("text")
    grep.add_argument("--volume")
    grep.add_argument("--limit", type=int, default=20)
    grep.add_argument("--start", type=int, default=1)
    return parser


def _ieee802_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource ieee802", description="IEEE 802 standards (GET Program)")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="import a PDF you obtained yourself")
    imp.add_argument("pdf")
    imp.add_argument("designation")
    commands.add_parser("outline", help="clauses from the PDF's bookmarks").add_argument("designation")
    return parser


def _run(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def posix_main(argv: Sequence[str]) -> int:
    args = _posix_parser().parse_args(list(argv))
    try:
        if args.command == "import":
            return importer.main(["posix", args.archive])
        if args.command == "pages":
            return _run("\n".join(posix.pages(args.volume)))
        if args.command == "outline":
            return _run(posix.outline(args.page))
        if args.command == "read":
            return _run(posix.read(args.ref, start=args.start, max_tokens=args.max_tokens))
        return _run(posix.grep(args.text, volume=args.volume, limit=args.limit, start=args.start))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1


def ieee802_main(argv: Sequence[str]) -> int:
    args = _ieee802_parser().parse_args(list(argv))
    try:
        if args.command == "import":
            return importer.main(["ieee802", args.pdf, args.designation])
        return _run(ieee802.outline(args.designation))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
