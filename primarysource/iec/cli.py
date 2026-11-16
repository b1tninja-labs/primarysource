"""`primarysource iec ...`: free Webstore sync for the owner's personal volume.

primarysource iec sync --free [--only ID_OR_REF ...] [--limit N] [--force]
primarysource iec list-free
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.iec import sync


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource iec", description="IEC Webstore free publications")
    commands = parser.add_subparsers(dest="command", required=True)
    sync_cmd = commands.add_parser("sync", help="order and download free publications from the local stubs")
    sync_cmd.add_argument("--free", action="store_true", required=True, help="every free stub (required)")
    sync_cmd.add_argument("--only", action="append", default=[], help="publication id or reference (repeatable)")
    sync_cmd.add_argument("--limit", type=int, default=0, help="stop after N free publications (0 = all)")
    sync_cmd.add_argument("--force", action="store_true", help="re-download even when the PDF is already on disk")
    listed = commands.add_parser("list-free", help="list free stubs under the iec home")
    for sub in (sync_cmd, listed):
        sub.add_argument("--home", type=Path, help="override the iec collection home")
    return parser


def _out(text: str) -> int:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    home = sync.default_home() if getattr(args, "home", None) is None else args.home
    try:
        if args.command == "list-free":
            pubs = sync.free_from_stubs(home / sync.STUBS)
            lines = [f"{p.publication_id}\t{p.head}\t{p.reference}" for p in pubs]
            return _out("\n".join(lines) if lines else f"no free stubs in {home / sync.STUBS}")
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
