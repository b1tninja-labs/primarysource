"""`primarysource draft ...`: the collection's own commands.

primarysource draft import <name>[-rev] ...   fetch drafts from the IETF (one request a second); --tracked for all
primarysource draft refresh [<name> ...]      fetch only the datatracker's current status; --tracked for all
primarysource draft list                      tracked and stored drafts, with state and replacement
primarysource draft info <name>               standing, revisions, expiry, replaced-by, licence legend
primarysource draft outline <name>[-rev]      a stored draft's sections
primarysource draft read <ref> [--start N] [--max-tokens N]
primarysource draft search <words> [--name N] [--limit N]
primarysource draft cite <ref>

`import` and `refresh` are the only commands that use the network. They refuse when `PRIMARYSOURCE_READONLY` is
set. The others read the library and are what the MCP tools call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence

from primarysource.draft import catalogue, importer, names, views
from primarysource.draft.net import Fetcher
from primarysource.draft.store import Store
from primarysource.errors import LibError

fetcher_factory: Callable[[], Fetcher] = Fetcher
"""How the importer gets its fetcher; tests replace it with one over a fake transport."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource draft", description="IETF Internet-Drafts")
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="fetch drafts from the IETF into the library")
    imp.add_argument("drafts", nargs="*", help="draft-<words>[-NN]; without -NN the latest revision")
    imp.add_argument("--tracked", action="store_true", help="every draft in the tracked catalogue (latest revision)")
    imp.add_argument("--no-xml", action="store_true", help="do not fetch the author's .xml")
    imp.add_argument("--sha256", help="expected sha256 of the .txt (one draft with an explicit revision only)")
    imp.add_argument("--print-pin", action="store_true", help="print each revision's digests as tracked.json pins")
    ref = commands.add_parser("refresh", help="fetch the datatracker's current status of drafts")
    ref.add_argument("drafts", nargs="*")
    ref.add_argument("--tracked", action="store_true", help="every draft in the tracked catalogue")
    commands.add_parser("list", help="tracked and stored drafts")
    commands.add_parser("info", help="standing of a draft").add_argument("name")
    commands.add_parser("outline", help="a stored draft's sections").add_argument("name")
    read = commands.add_parser("read", help="read by ref")
    read.add_argument("ref")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--max-tokens", type=int, default=2000)
    search = commands.add_parser("search", help="search the stored drafts")
    search.add_argument("query")
    search.add_argument("--name")
    search.add_argument("--limit", type=int, default=10)
    commands.add_parser("cite", help="the citation for a ref").add_argument("ref")
    return parser


def _emit(text: str) -> int:
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8")  # refs carry §, and a Windows console pipe is not UTF-8 by default
    out.write(text if text.endswith("\n") else text + "\n")
    return 0


def _targets(args: argparse.Namespace) -> list[tuple[str, str | None]]:
    found = [names.split_doc(d) for d in args.drafts]
    if args.tracked:
        found += [(n, None) for n in catalogue.TRACKED if n not in {f[0] for f in found}]
    if not found:
        raise LibError(
            "name a draft, or pass --tracked", "e.g. primarysource draft import draft-ietf-sidrops-8210bis"
        )
    return found


def _import(args: argparse.Namespace, store: Store) -> int:
    targets = _targets(args)
    if args.sha256 and (len(targets) != 1 or targets[0][1] is None):
        raise LibError(
            "--sha256 needs exactly one draft with an explicit revision", "e.g. draft-x-y-03 --sha256 <hex>"
        )
    fetcher = fetcher_factory()
    failed = 0
    pins: dict[str, dict[str, dict[str, str]]] = {}
    for name, rev in targets:
        try:
            report = importer.import_draft(
                name, rev, fetcher=fetcher, store=store, want_xml=not args.no_xml, expected_sha256=args.sha256
            )
        except LibError as exc:
            failed += 1
            print(f"{name}: {exc.message}" + (f" ({exc.hint})" if exc.hint else ""), file=sys.stderr)
            continue
        verb = "imported" if report.new else "already stored"
        pin = "pinned" if report.pinned else "not pinned (trusted on first use)"
        print(
            f"{report.name}-{report.rev}: {verb}, text {report.txt_bytes:,} bytes sha256 {report.txt_sha256}, "
            f"xml {report.xml_state}, state {report.status.state}, {pin}, {report.requests} requests -> {report.path}"
        )
        if report.xml_sha256 or report.txt_sha256:
            pins.setdefault(report.name, {})[report.rev] = {
                "txt": report.txt_sha256,
                **({"xml": report.xml_sha256} if report.xml_sha256 else {}),
            }
    if args.print_pin and pins:
        print(json.dumps(pins, indent=1))
    return 1 if failed else 0


def _refresh(args: argparse.Namespace, store: Store) -> int:
    fetcher = fetcher_factory()
    failed = 0
    for name, _rev in _targets(args):
        try:
            status = importer.refresh(name, fetcher=fetcher, store=store)
        except LibError as exc:
            failed += 1
            print(f"{name}: {exc.message}" + (f" ({exc.hint})" if exc.hint else ""), file=sys.stderr)
            continue
        extra = (f", replaced by {', '.join(status.replaced_by)}" if status.replaced_by else "") + (
            f", became {status.became_rfc}" if status.became_rfc else ""
        )
        print(f"{name}: latest -{status.rev}, state {status.state}, expires {status.expires[:10] or '?'}{extra}")
    return 1 if failed else 0


def main(argv: Sequence[str]) -> int:
    args = _parser().parse_args(list(argv))
    store = Store()
    try:
        if args.command == "import":
            return _import(args, store)
        if args.command == "refresh":
            return _refresh(args, store)
        if args.command == "list":
            return _emit(views.list_tracked(store))
        if args.command == "info":
            return _emit(views.info(store, args.name))
        if args.command == "outline":
            return _emit(views.outline(store, args.name))
        if args.command == "read":
            return _emit(views.read(store, args.ref, start=args.start, max_tokens=args.max_tokens))
        if args.command == "search":
            return _emit(views.search(store, args.query, limit=args.limit, name=args.name))
        return _emit(views.cite(store, args.ref))
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
