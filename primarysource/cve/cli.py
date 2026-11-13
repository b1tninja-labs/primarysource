"""`primarysource cve ...`: the same answers as the MCP tools, as the same text; `--json` prints `service`'s dict.

A failure prints the `error:`, `hint:` and `action:` lines of a `LibError` on stderr and exits 2 (PLAN.md §5.10)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from primarysource.errors import LibError

from . import __version__, config, service, views
from .sync import sync as run_sync


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="primarysource cve", description="Local vulnerability corpus and MCP server."
    )
    parser.add_argument("--version", action="version", version=f"primarysource cve {__version__}")
    parser.add_argument("--json", action="store_true", help="print the raw JSON answer")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("path", help="show CVELIB_HOME and the index path")

    info = commands.add_parser("info", help="corpus status, or a card for one CVE")
    info.add_argument("ref", nargs="?", default="")

    search = commands.add_parser("search", help="full-text search")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--start", type=int, default=0)
    search.add_argument("--kev", action="store_true")
    search.add_argument("--kernel", action="store_true")
    search.add_argument("--year", type=int, default=0)

    read = commands.add_parser("read", help="one CVE, merged across sources (CVE-Y-N or CVE-Y-N§section)")
    read.add_argument("ref")
    read.add_argument("--max-tokens", type=int, default=2000)

    kev = commands.add_parser("kev", help="CISA KEV status for a CVE, or the catalog newest first")
    kev.add_argument("ref", nargs="?", default="")
    kev.add_argument("--vendor", default="")
    kev.add_argument("--since", default="")
    kev.add_argument("--limit", type=int, default=20)
    kev.add_argument("--start", type=int, default=0)

    kernel = commands.add_parser("kernel", help="does this CVE affect this kernel version")
    kernel.add_argument("ref")
    kernel.add_argument("version")

    kernel_list = commands.add_parser("kernel-list", help="every kernel CNA CVE that affects a version")
    kernel_list.add_argument("version")
    kernel_list.add_argument("--kev", action="store_true")
    kernel_list.add_argument("--path", default="")
    kernel_list.add_argument("--limit", type=int, default=25)
    kernel_list.add_argument("--start", type=int, default=0)

    sync = commands.add_parser("sync", help="fetch the sources and update the index")
    sync.add_argument(
        "--source", default=",".join(config.SOURCES), help="comma list of: " + ", ".join(config.SOURCES)
    )
    sync.add_argument("--kernel-tree", type=Path, help="ingest an existing vulns.git checkout instead of fetching")
    sync.add_argument("--cvelist-zip", type=Path, help="ingest a local CVE List release zip instead of fetching")
    sync.add_argument("--force", action="store_true", help="ignore the free-space check and any ETag")
    sync.add_argument("--full", action="store_true", help="take the CVE List baseline even if a delta would do")

    commands.add_parser("mcp", help="run the MCP server on stdio")
    return parser


def _show(args: argparse.Namespace, payload: dict[str, Any], view: Callable[[dict[str, Any]], str]) -> None:
    if args.json:
        _print_json(payload)
    else:
        print(view(payload), end="")


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command == "path":
        if args.json:
            _print_json({"home": str(config.home()), "index": str(config.index_path()), "env": "CVELIB_HOME"})
        else:
            print(views.path(str(config.home()), str(config.index_path())), end="")
    elif command == "info":
        _show(args, service.info(args.ref), views.info)
    elif command == "search":
        payload = service.search(" ".join(args.query), args.limit, args.start, args.kev, args.kernel, args.year)
        _show(args, payload, views.search)
    elif command == "read":
        _show(args, service.read(args.ref, args.max_tokens), views.read)
    elif command == "kev":
        _show(args, service.kev(args.ref, args.vendor, args.since, args.limit, args.start), views.kev)
    elif command == "kernel":
        _show(args, service.kernel_check(args.ref, args.version), views.kernel_check)
    elif command == "kernel-list":
        payload = service.kernel_list(args.version, args.kev, args.path, args.limit, args.start)
        _show(args, payload, views.kernel_list)
    elif command == "sync":
        results = run_sync(
            [item.strip() for item in args.source.split(",") if item.strip()],
            args.kernel_tree,
            args.cvelist_zip,
            args.force,
            args.full,
        )
        for name, outcome in results.items():
            print(f"{name}: {outcome}")
        return 1 if any(value.startswith("FAILED") for value in results.values()) else 0
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    # Record text holds characters a Windows console's code page has no room for; a command whose job is to print
    # it must not die on one.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = _parser().parse_args(argv)
    if args.command == "mcp":
        from .mcp import main as serve

        try:
            serve()
        except ImportError as error:
            print(error, file=sys.stderr)
            return 2
        return 0
    try:
        return _dispatch(args)
    except LibError as error:
        print(error.as_text(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
