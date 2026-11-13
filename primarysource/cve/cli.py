"""Command line: the same answers as the MCP server, printed for a person (or as JSON with --json)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__, config, service
from .errors import CvelibError
from .sync import sync as run_sync


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _render_search(payload: dict[str, Any]) -> None:
    for hit in payload["hits"]:
        flags = "".join(
            [
                f" cvss={hit['cvss']}" if "cvss" in hit else "",
                " KEV" if hit.get("kev") else "",
                f" epss={hit['epss']:.3f}" if "epss" in hit else "",
            ]
        )
        print(f"{hit['ref']}  [{hit['source']}]{flags}  {hit['title']}")
    if not payload["hits"]:
        print("(no matches)")
    _render_tail(payload)


def _render_kernel_list(payload: dict[str, Any]) -> None:
    print(f"{payload['version']}: {payload['affected_total']} of {payload['assessed']} kernel CNA CVEs affect it")
    print(f"source: {payload['source']}")
    for item in payload["items"]:
        marks = " KEV" if item.get("kev") else ""
        print(f"{item['ref']}{marks}  {item['title']}  ({item['why']})")
    _render_tail(payload)


def _render_tail(payload: dict[str, Any]) -> None:
    for line in payload.get("caveats", []):
        print(f"caveat: {line}")
    for line in payload.get("partial", []):
        print(f"partial: {line}")
    if "relaxed" in payload:
        print(f"note: {payload['relaxed']}")
    if "next" in payload:
        print(f"next: {payload['next']}")


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


def _dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command == "path":
        _print_json({"home": str(config.home()), "index": str(config.index_path()), "env": "CVELIB_HOME"})
    elif command == "info":
        _print_json(service.info(args.ref))
    elif command == "search":
        payload = service.search(" ".join(args.query), args.limit, args.start, args.kev, args.kernel, args.year)
        _print_json(payload) if args.json else _render_search(payload)
    elif command == "read":
        _print_json(service.read(args.ref, args.max_tokens))
    elif command == "kev":
        _print_json(service.kev(args.ref, args.vendor, args.since, args.limit))
    elif command == "kernel":
        _print_json(service.kernel_check(args.ref, args.version))
    elif command == "kernel-list":
        payload = service.kernel_list(args.version, args.kev, args.path, args.limit, args.start)
        _print_json(payload) if args.json else _render_kernel_list(payload)
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
    except CvelibError as error:
        print(f"error: {error.message}", file=sys.stderr)
        if error.hint:
            print(f"hint: {error.hint}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
