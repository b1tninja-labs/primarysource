"""`primarysource bluetooth ...`: the collection's own commands.

catalogue                       read the SIG's list of specifications (one request) into the home
list [--status S] [--search W]  show the cached catalogue
fetch [SLUG ...] [--status S]   download, pin, extract and index (default: every adopted specification)
      [--dry-run] [--force] [--repin]
index                           rebuild the search index from the imported text
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from primarysource.errors import LibError


def _catalogue(args: argparse.Namespace) -> int:
    from primarysource.bluetooth import importer, paths

    entries = importer.refresh_catalogue(paths.home(), importer.new_fetcher())
    kinds: dict[str, int] = {}
    for entry in entries:
        kinds[entry.status] = kinds.get(entry.status, 0) + 1
    counts = ", ".join(f"{n} {s.lower()}" for s, n in sorted(kinds.items()))
    print(f"{len(entries)} documents ({counts}) -> {paths.home()}")
    return 0


def _list(args: argparse.Namespace) -> int:
    from primarysource.bluetooth import catalogue, importer, paths

    entries = importer.select(catalogue.read(paths.home() / "catalogue.json"), [], args.status)
    for entry in entries:
        line = f"{entry.slug}  {entry.title} {entry.revision}  [{entry.status}]"
        if args.search is None or args.search.lower() in line.lower():
            print(line)
    return 0


def _fetch(args: argparse.Namespace) -> int:
    from primarysource.bluetooth import catalogue, importer, paths
    from primarysource.bluetooth.spec import SPEC

    home = paths.home()
    fetcher = importer.new_fetcher()
    cached = home / "catalogue.json"
    entries = catalogue.read(cached) if cached.is_file() else importer.refresh_catalogue(home, fetcher)
    chosen = importer.select(entries, args.slugs, args.status)
    if args.dry_run:
        minutes = 2 * len(chosen) * importer.CRAWL_DELAY / 60
        pace = f"one every {importer.CRAWL_DELAY:.0f} s, ~{minutes:.0f} min"
        print(f"would fetch up to {len(chosen)} documents: 2 requests each, {pace}")
        return 0
    print(f"{len(chosen)} documents, one request every {importer.CRAWL_DELAY:.0f} s", flush=True)

    def show(outcome: importer.Outcome) -> None:
        detail = (
            f"{outcome.pages} pages, {outcome.sections} sections ({outcome.note})"
            if outcome.status == "imported"
            else outcome.note
        )
        print(f"{outcome.status:<9} {outcome.slug}  {detail}".rstrip(), flush=True)

    report = importer.fetch_specs(SPEC, chosen, fetcher, home=home, force=args.force, repin=args.repin, progress=show)
    if report.indexed_sections:
        print(f"indexed {report.indexed_sections} section(s) into {SPEC.corpus_dir()}")
    return 1 if any(o.status in ("failed", "changed") for o in report.outcomes) else 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="primarysource bluetooth", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("catalogue", help="read the SIG's list of specifications into the home")
    listing = commands.add_parser("list", help="show the cached catalogue")
    listing.add_argument("--status", default="any", help="adopted, draft, approved or any (default)")
    listing.add_argument("--search", help="only lines containing this text")
    fetch = commands.add_parser("fetch", help="download, pin, extract and index specifications")
    fetch.add_argument("slugs", nargs="*", help="documents by slug (see `list`); default: every one with --status")
    fetch.add_argument("--status", default="adopted", help="which to fetch when no slug is given (default: adopted)")
    fetch.add_argument("--dry-run", action="store_true", help="say how many and how long, fetch nothing")
    fetch.add_argument("--force", action="store_true", help="fetch again what is already imported")
    fetch.add_argument("--repin", action="store_true", help="accept a PDF whose sha256 differs from its pin")
    commands.add_parser("index", help="rebuild the search index from the imported text")
    args = parser.parse_args(list(argv))
    try:
        if args.command == "index":
            from primarysource.bluetooth.spec import SPEC
            from primarysource.pdfcorpus import fts

            return fts.main(SPEC, [])
        return {"catalogue": _catalogue, "list": _list, "fetch": _fetch}[args.command](args)
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 2
