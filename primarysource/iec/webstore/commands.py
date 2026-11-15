"""`python -m primarysource.iec.webstore <command>`: the SDK from a shell. The coordinator wires it into the CLI.

    search    one page of live search (public API, no login)
    sync      opt-in, bounded: write catalogue stubs under the collection home and rebuild the index
    find      search the local catalogue index (no network)
    owned     the items in the owner's orders (login from the environment)
    download  download an owned order or item to a directory outside every repository
    cart      add an item to the cart: a dry run unless confirmed
    order     place an order for a zero-total cart: a dry run unless confirmed

Credentials come only from PRIMARYSOURCE_IEC_USERNAME / PRIMARYSOURCE_IEC_PASSWORD (or a cookie jar named by
PRIMARYSOURCE_IEC_SESSION_FILE). Nothing here prints a credential, a cookie or an address.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from primarysource.errors import LibError
from primarysource.iec.webstore._secret import SESSION_FILE_VARIABLE, Credentials
from primarysource.iec.webstore.cart import BillingAddress, Confirmation, ItemChoice, Plan, Shop
from primarysource.iec.webstore.catalog import HARD_MAX_PAGES, catalog_home, filter_catalog, find, sync_catalog
from primarysource.iec.webstore.models import Publication
from primarysource.iec.webstore.orders import OrderClient
from primarysource.iec.webstore.search import SearchClient, SearchQuery
from primarysource.iec.webstore.session import IecSession
from primarysource.iec.webstore.transport import PoliteTransport, UrllibTransport, ensure_outside_repository

__all__ = ["main"]


def _transport(environ: Mapping[str, str]) -> tuple[PoliteTransport, UrllibTransport]:
    session_file = environ.get(SESSION_FILE_VARIABLE)
    inner = UrllibTransport(session_file=Path(session_file) if session_file else None)
    return PoliteTransport(inner, environ=environ), inner


def _login(environ: Mapping[str, str]) -> tuple[IecSession, UrllibTransport]:
    transport, inner = _transport(environ)
    session = IecSession(transport)
    if environ.get(SESSION_FILE_VARIABLE) and session.is_logged_in():
        return session, inner
    session.login(Credentials.from_env(environ))
    inner.save_session()
    return session, inner


def _line(p: Publication) -> str:
    price = str(p.price) if p.price else "no price"
    return f"{p.id}\t{p.reference}\t{p.edition}\t{p.status}\t{price}\t{p.title}"


def _query(args: argparse.Namespace) -> SearchQuery:
    facets: dict[str, list[str]] = {}
    for spec in args.facet or ():
        name, _, value = spec.partition("=")
        if not name or not value:
            raise LibError(f"--facet {spec!r} is not name=value", "e.g. --facet committee='TC 86' --facet type=IS")
        facets.setdefault(name, []).append(value)
    return SearchQuery(text=args.text or "").with_terms(**facets)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="primarysource.iec.webstore", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def search_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("text", nargs="?", default="")
        p.add_argument("--facet", action="append", metavar="NAME=VALUE")

    p = sub.add_parser("search", help="one page of live search")
    search_args(p)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--size", type=int, default=25)
    p = sub.add_parser("sync", help="opt-in, bounded catalogue sync")
    search_args(p)
    p.add_argument("--i-have-read-the-terms", action="store_true", dest="opt_in")
    p.add_argument("--max-pages", type=int, default=1, help=f"1..{HARD_MAX_PAGES} pages of 100")
    p.add_argument("--no-abstract", action="store_true", help="leave the store's catalogue abstract out")
    p = sub.add_parser("filter", help="filter the local catalogue by cost, category and status")
    p.add_argument("--free", action="store_true")
    p.add_argument("--min-price", type=float)
    p.add_argument("--max-price", type=float)
    p.add_argument("--category", help="prefix: a committee (TC 86), an ICS code (33.100), a type, a head")
    p.add_argument("--status")
    p = sub.add_parser("find", help="search the local catalogue")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=8)
    p = sub.add_parser("owned", help="items in the owner's recent orders")
    p.add_argument("--max-orders", type=int, default=10)
    p = sub.add_parser("download", help="download an owned order or item")
    p.add_argument("--to", required=True, help="a directory outside every repository")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--order")
    group.add_argument("--item")
    p = sub.add_parser("cart", help="add to cart: dry run unless confirmed")
    p.add_argument("publication", type=int)
    p.add_argument("--language", default="English")
    p.add_argument("--format", default="Electronic")
    p.add_argument("--users", default="1")
    p.add_argument("--confirm-reference")
    p.add_argument("--confirm-total", type=float)
    p = sub.add_parser("order", help="place a zero-total order: dry run unless confirmed")
    p.add_argument("--billing-json", required=True, help="a JSON file outside every repository")
    p.add_argument("--confirm-reference")
    p.add_argument("--confirm-total", type=float)
    p.add_argument("--accept-terms", action="store_true")
    return parser


def _billing(path: str) -> BillingAddress:
    data = json.loads(ensure_outside_repository(Path(path)).read_text("utf-8"))
    try:
        return BillingAddress(
            data["first_name"],
            data["last_name"],
            tuple(data["street"]),
            data["city"],
            data["postcode"],
            data["country_id"],
            data["telephone"],
            data.get("region", ""),
            str(data.get("region_id", "")),
            data.get("region_code", ""),
        )
    except KeyError as error:
        raise LibError(f"the billing file lacks {error}", "see docs/iec-webstore.md, 'Free order'") from error


def _confirmation(args: argparse.Namespace) -> Confirmation | None:
    if args.confirm_reference is None and args.confirm_total is None:
        return None
    if args.confirm_reference is None or args.confirm_total is None:
        raise LibError("a confirmation needs both --confirm-reference and --confirm-total", "pass both, or neither")
    return Confirmation(args.confirm_reference, args.confirm_total, accept_terms=getattr(args, "accept_terms", False))


def run(args: argparse.Namespace, environ: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    if args.command == "search":
        transport, _ = _transport(environ)
        page = SearchClient(transport).search(_query(args), start=args.start, size=args.size)
        out.extend(_line(p) for p in page.hits)
        out.append(f"total: {page.total}")
        if page.next_start is not None:
            out.append(f"next: --start {page.next_start}")
    elif args.command == "sync":
        transport, _ = _transport(environ)
        home = catalog_home()
        written, total = sync_catalog(
            SearchClient(transport),
            home,
            _query(args),
            opt_in=args.opt_in,
            max_pages=args.max_pages,
            include_abstract=not args.no_abstract,
        )
        out.append(f"wrote {written} stubs of {total} matching, under {home}")
    elif args.command == "filter":
        for stub in filter_catalog(
            catalog_home(),
            free_only=args.free,
            min_price=args.min_price,
            max_price=args.max_price,
            category_prefix=args.category,
            status=args.status,
        ):
            price = stub.get("price")
            shown = f"{price['currency']} {price['amount']:g}" if price else "no price"
            out.append(
                f"{stub['id']}	{stub['reference']}	{stub.get('status', '')}	{shown}	{stub.get('title', '')}"
            )
    elif args.command == "find":
        hits, relaxed, more = find(catalog_home(), args.query, limit=args.limit)
        out.extend(f"{h.id}\t{h.reference}\t{h.section}\t{h.snippet}" for h in hits)
        if relaxed:
            out.append("relaxed: only some terms matched")
        if more is not None:
            out.append(f"next: {more}")
    elif args.command == "owned":
        session, _ = _login(environ)
        out.extend(
            f"{o}\t{i.reference}\t{i.language}\t{i.format}\tx{i.quantity}\t{i.price}"
            for o, i in OrderClient(session).owned(max_orders=args.max_orders)
        )
    elif args.command == "download":
        session, _ = _login(environ)
        result = OrderClient(session).download(Path(args.to), order_id=args.order, item_id=args.item)
        out.append(f"{result.path}\t{result.size} bytes\tsha256 {result.sha256}")
    elif args.command == "cart":
        session, _ = _login(environ)
        plan = Shop(session).add_to_cart(
            args.publication, ItemChoice(args.language, args.format, args.users), _confirmation(args)
        )
        out.append(_plan(plan.action, plan.reference, plan.total, plan.currency, plan.steps, plan.executed))
    else:
        session, _ = _login(environ)
        outcome = Shop(session).order_free(_billing(args.billing_json), _confirmation(args))
        if isinstance(outcome, Plan):
            out.append(
                _plan(outcome.action, outcome.reference, outcome.total, outcome.currency, outcome.steps, False)
            )
        else:
            out.append(
                f"ordered {outcome.reference}: order {outcome.order_id}; download it with the download command"
            )
    return out


def _plan(
    action: str, reference: str, total: float | None, currency: str, steps: Sequence[str], executed: bool
) -> str:
    shown = total if total is not None else "?"
    head = f"{'DONE' if executed else 'DRY RUN'} {action}: {reference} total {shown} {currency}"
    return "\n".join([head, *(f"  {s}" for s in steps)])


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        for line in run(args, os.environ if environ is None else environ):
            print(line)  # noqa: T201
    except LibError as error:
        print(error.as_text())  # noqa: T201
        return 1
    return 0
