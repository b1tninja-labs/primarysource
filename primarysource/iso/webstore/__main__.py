"""`python -m primarysource.iso.webstore <command>`: the owner's command line for the webstore client.

Offline (no network, no credentials):
  load FILE.jsonl        write catalog stubs from a JSON-lines file of catalog records (e.g. one the owner exported)
  index                  rebuild the catalog index from the stubs
  find QUERY             keyword search over the stubs, with --category/--status/--free/--priced
  browse CATEGORY        list the stored records of one category (ics, committee, standard)

Online, catalog only (one request a second, never any credentials):
  search QUERY           one page of the site's catalog search
  sync QUERY... --i-accept-the-terms    bounded stub sync (see docs/iso-webstore.md section 7)

Online, signed in (PRIMARYSOURCE_ISO_USERNAME / PRIMARYSOURCE_ISO_PASSWORD):
  whoami, basket, owned, plan-free-order
  free-order --item DESC... --expected-total 0 --accept-withdrawal-consent    (the only command that places an order)
  download DESIGNATION [--dest DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from primarysource.errors import LibError
from primarysource.iso.webstore import (
    Basket,
    CatalogEntry,
    CatalogFilter,
    CatalogSearch,
    CatalogStore,
    Credentials,
    FreeOrderConfirmation,
    GraphQLClient,
    ObpSession,
    SessionCache,
    WebstoreSession,
    download_owned,
    sign_in,
    sync_catalog,
)
from primarysource.iso.webstore.auth import OBP_LOGIN, login
from primarysource.iso.webstore.models import entries_from_summary


def _decimal(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not an amount") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m primarysource.iso.webstore", description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, help="the webstore folder (default: <iso home>/webstore)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("load").add_argument("file", type=Path)
    sub.add_parser("index")
    find = sub.add_parser("find")
    find.add_argument("query", nargs="?", help="keywords; omit to filter only")
    find.add_argument("--min-price", type=_decimal)
    find.add_argument("--max-price", type=_decimal)
    find.add_argument("--ics-prefix")
    find.add_argument("--tc-prefix")
    find.add_argument("--language")
    find.add_argument("--category")
    find.add_argument("--status")
    group = find.add_mutually_exclusive_group()
    group.add_argument("--free", action="store_true")
    group.add_argument("--priced", action="store_true")
    sub.add_parser("browse").add_argument("category")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--category")
    search.add_argument("--page", type=int, default=0)
    sync = sub.add_parser("sync")
    sync.add_argument("queries", nargs="+")
    sync.add_argument("--category")
    sync.add_argument("--max-pages", type=int, default=2)
    sync.add_argument("--i-accept-the-terms", action="store_true", dest="opt_in")
    for name in ("whoami", "basket", "owned", "plan-free-order"):
        sub.add_parser(name)
    free = sub.add_parser("free-order")
    free.add_argument(
        "--item", action="append", required=True, help="an order line's description, as the plan shows it"
    )
    free.add_argument("--expected-total", type=_decimal, required=True)
    free.add_argument("--accept-withdrawal-consent", action="store_true")
    free.add_argument(
        "--summary-to-stubs", action="store_true", help="also write the placed order's standards as stubs"
    )
    dl = sub.add_parser("download")
    dl.add_argument("designation", help="as 'owned' prints it")
    dl.add_argument("--dest", type=Path)
    return parser


def _signed_in() -> tuple[WebstoreSession, GraphQLClient]:
    session = WebstoreSession()
    graphql = GraphQLClient(session)
    sign_in(session, graphql, Credentials.from_env(), SessionCache.from_env())
    return session, graphql


def _line(entry: CatalogEntry) -> str:
    price = "" if entry.price is None else f"  {'free' if entry.price.is_free else entry.price}"
    return f"{entry.kind:<10} {entry.designation or '-':<28} {entry.status or '-':<14} {entry.title}{price}"


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = CatalogStore(args.root)
    cmd = args.command
    if cmd == "load":
        entries = [
            CatalogEntry.from_json(json.loads(line))
            for line in args.file.read_text("utf-8").splitlines()
            if line.strip()
        ]
        print(f"wrote {store.write_all(entries)} stubs under {store.stubs}")
    elif cmd == "index":
        print(f"indexed {store.build_index()} records into {store.index_path}")
    elif cmd == "find":
        free = True if args.free else False if args.priced else None
        where = CatalogFilter(
            args.category,
            args.status,
            free,
            args.min_price,
            args.max_price,
            args.ics_prefix,
            args.tc_prefix,
            args.language,
        )
        for entry in store.select(where, args.query):
            print(_line(entry))
    elif cmd == "browse":
        for entry in store.browse(args.category):
            print(_line(entry))
    elif cmd == "search":
        page = CatalogSearch(WebstoreSession()).search(args.query, category=args.category, page=args.page)
        for entry in page.hits:
            print(_line(entry))
        print(f"page {page.page + 1} of {page.pages}, {page.total} hits")
    elif cmd == "sync":
        report = sync_catalog(
            CatalogSearch(WebstoreSession()),
            store,
            args.queries,
            opt_in=args.opt_in,
            max_pages=args.max_pages,
            category=args.category,
        )
        print(
            f"{report.queries} queries, {report.requests} requests, {report.written} stubs written; run `index` next"
        )
    elif cmd == "whoami":
        _, graphql = _signed_in()
        from primarysource.iso.webstore.auth import who_am_i

        state = who_am_i(graphql)
        print(
            f"signed in: {state.signed_in}; roles: {', '.join(state.roles) or '-'}; "
            f"language: {state.preferred_language}"
        )
    elif cmd in ("basket", "plan-free-order", "free-order"):
        session, graphql = _signed_in()
        basket = Basket(session, graphql)
        if cmd == "basket":
            counter = basket.summary()
            print(f"{counter.item_count} items, {counter.total} {counter.currency}")
        elif cmd == "plan-free-order":
            plan = basket.plan_free_order()
            for item in plan.order.items:
                print(f"line: {item.description!r} {item.format} {item.unit_price} {item.currency}")
            print(f"total: {plan.order.total} {plan.order.currency}")
            print("problems: " + ("; ".join(plan.problems) or "none: the guards pass"))
        else:
            confirm = FreeOrderConfirmation(frozenset(args.item), args.expected_total, args.accept_withdrawal_consent)
            result = basket.free_order(confirm)
            summary = result.summary
            print(f"order {summary.status if summary else '?'}; total {summary.total if summary else '?'}")
            if summary and args.summary_to_stubs:
                store.write_all(entries_from_summary(summary))
    elif cmd in ("owned", "download"):
        session, _ = _signed_in()
        login(session, Credentials.from_env(), start=OBP_LOGIN)
        obp = ObpSession(session)
        obp.open()
        products = obp.products()
        if cmd == "owned":
            for product in products:
                readiness = (
                    "ready"
                    if product.download_paths
                    else "licence unassigned"
                    if product.assign_button
                    else "no download"
                )
                print(f"{product.designation} ({product.language}) {product.title}  [{readiness}]")
        else:
            wanted = [p for p in products if p.designation == args.designation.strip()]
            if len(wanted) != 1 or not wanted[0].download_paths:
                raise LibError(
                    f"{args.designation!r} is not ready to download",
                    "run `owned`; assign the licence in the platform first",
                )
            done = download_owned(session, wanted[0].download_paths[0], args.dest)
            print(f"{done.path} {done.size} bytes sha256 {done.sha256}{' (already there)' if done.reused else ''}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(argv)
    except LibError as error:
        print(error.as_text(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
