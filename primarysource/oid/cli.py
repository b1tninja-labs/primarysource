"""`primarysource oid ...`.

primarysource oid roots
primarysource oid read <0|1|2>
primarysource oid export
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.oid import library


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource oid", description="Root arcs 0, 1 and 2")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("roots", help="arcs 0, 1 and 2 from the imported X.660")
    reading = commands.add_parser("read", help="one root arc")
    reading.add_argument("ref")
    commands.add_parser("export", help="the oid-node/1 JSON document")
    return parser


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    try:
        if args.command == "roots":
            text = library.roots()
        elif args.command == "read":
            text = library.read(args.ref)
        else:
            text = library.export()
    except LibError as exc:
        sys.stderr.write(exc.as_text() + "\n")
        return 1
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0
