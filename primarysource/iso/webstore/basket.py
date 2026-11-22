"""The basket and the free order, with every state-changing call dry-run until it is confirmed.

Two calls change anything here:

- `Basket.add` is `GET /webstore/MiniShoppingBasket?memberId=ISO&purchaseId=<id>`. A GET that adds a line to the
  session's basket; it answers `{itemCount, totalAmount, currency}` for the whole basket.
- `Basket.free_order` is the GraphQL mutation `processFreeOrder`.

Both take an optional confirmation object. Without one they make no state-changing request and return what they
would do. With one they check it against what the server reports, and refuse on any difference. Paying is not
implemented at all: there is no code path here that sends payment details.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from primarysource.errors import LibError
from primarysource.iso.webstore.graphql import (
    CURRENT_ORDER,
    ORDER_SUMMARY,
    PROCESS_FREE_ORDER,
    GraphQLClient,
)
from primarysource.iso.webstore.models import Order, OrderSummary, money, parse_order, parse_summary
from primarysource.iso.webstore.session import BASE, WebstoreSession

MEMBER_ID = "ISO"
"""The `memberId` the capture shows for the ISO store itself; national bodies' stores use their own."""
ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class BasketCounter:
    """`{itemCount, totalAmount, currency}`, the answer of both basket endpoints."""

    item_count: int
    total: Decimal
    currency: str


def _counter(body: bytes, what: str) -> BasketCounter:
    try:
        data = json.loads(body)
        return BasketCounter(
            int(data["itemCount"]), money(data["totalAmount"], what), str(data.get("currency") or "")
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise LibError(
            f"{what}: the answer is not a basket summary", "retry later; the session may have expired"
        ) from exc


@dataclass(frozen=True, slots=True)
class AddConfirmation:
    """Permission to add one item. `item` names it for the record (a designation); `purchase_id` is the id the
    request carries; `expected_total` is the basket total, in the basket's currency, expected after the add."""

    purchase_id: str
    item: str
    expected_total: Decimal


@dataclass(frozen=True, slots=True)
class FreeOrderConfirmation:
    """Permission to place the current basket as a free order.

    `items` are the descriptions the order shows (`ISO/IEC 26136`), exactly those and no others. `expected_total`
    must be zero. `accept_withdrawal_consent` is sent as `isWithdrawalConsentAccepted`; the webstore requires it, and
    it is the buyer's statement, so it is never defaulted to True. The two optional consents default to refused.
    """

    items: frozenset[str]
    expected_total: Decimal
    accept_withdrawal_consent: bool
    share_data: bool = False
    email_notifications: bool = False


@dataclass(frozen=True, slots=True)
class AddResult:
    executed: bool
    request: str
    """The request that was (or would be) made, with the purchase id shown as its length only."""
    basket: BasketCounter | None = None


@dataclass(frozen=True, slots=True)
class FreeOrderResult:
    executed: bool
    order: Order
    problems: tuple[str, ...]
    """Why this basket cannot be placed as a free order. Empty means the guards pass."""
    summary: OrderSummary | None = None
    would_send: dict[str, Any] = field(default_factory=dict)
    """The mutation's variables with the checksum redacted, for the record."""


class Basket:
    def __init__(
        self,
        session: WebstoreSession,
        graphql: GraphQLClient,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._session = session
        self._graphql = graphql
        self._now = now

    # --- reads ---

    def summary(self) -> BasketCounter:
        """`GET /webstore/shoppingbasket/summary`: item count and total. Changes nothing."""
        stamp = int(self._now() * 1000)
        response = self._session.request("GET", f"{BASE}/webstore/shoppingbasket/summary?_={stamp}", follow=False)
        if response.status != 200:
            raise LibError(f"basket summary: HTTP {response.status}", "sign in again, then retry")
        return _counter(response.body, "the basket total")

    def current_order(self) -> Order:
        data = self._graphql.execute("currentOrder", CURRENT_ORDER)
        raw = data.get("currentOrder")
        if not isinstance(raw, dict):
            raise LibError("there is no current order", "the basket is empty or the session expired")
        return parse_order(raw)

    def order_summary(self, order_id: str) -> OrderSummary:
        data = self._graphql.execute("orderSummary", ORDER_SUMMARY, {"orderId": order_id})
        raw = data.get("orderSummary")
        if not isinstance(raw, dict):
            raise LibError("no such order summary", "check the order number")
        return parse_summary(raw)

    # --- add ---

    def add(self, purchase_id: str, confirm: AddConfirmation | None = None) -> AddResult:
        """Add one item. Dry-run unless `confirm` names this `purchase_id` and the total expected afterwards.

        `purchase_id` is four ids joined with `~` (price book, an id this capture does not name, format, edition); the
        webstore hands it out inside the browsing platform. After the add the answer's total is compared with
        `confirm.expected_total`; if it differs the item is already in the basket (removing it is
        `deleteOrderItem`, which this client does not implement) and the call raises, saying so.
        """
        if purchase_id.count("~") != 3 or not all(purchase_id.split("~")):
            raise LibError("not a purchase id", "it is four ids joined by '~', taken from the browsing platform")
        query = urllib.parse.urlencode({"memberId": MEMBER_ID, "purchaseId": purchase_id})
        shown = f"GET {BASE}/webstore/MiniShoppingBasket?memberId={MEMBER_ID}&purchaseId=<{len(purchase_id)} chars>"
        if confirm is None:
            return AddResult(False, shown)
        if confirm.purchase_id != purchase_id or not confirm.item.strip():
            raise LibError(
                "the confirmation names a different item than the request", "build it from the same purchase id"
            )
        response = self._session.request("GET", f"{BASE}/webstore/MiniShoppingBasket?{query}", follow=False)
        if response.status != 200:
            raise LibError(f"add to basket: HTTP {response.status}", "check the basket in a browser before retrying")
        counter = _counter(response.body, "the basket total after the add")
        if counter.total != confirm.expected_total:
            raise LibError(
                f"after adding {confirm.item!r} the basket total is {counter.total} {counter.currency}, "
                f"not the expected {confirm.expected_total}",
                "the item is in the basket: remove it in a browser, and do not place the order",
            )
        return AddResult(True, shown, counter)

    # --- the free order ---

    def plan_free_order(self) -> FreeOrderResult:
        """What `free_order` would do, from the current order. Reads only."""
        return self.free_order(None)

    def free_order(self, confirm: FreeOrderConfirmation | None = None) -> FreeOrderResult:
        """Place the current basket as a free order, or say why it cannot be.

        Refused unless the server's own figures are all zero (total, tax, shipping and every line), nothing in it
        ships, and its lines are exactly the confirmed ones. The checksum is read from the order just before the call,
        so the server decides what it covers.
        """
        order = self.current_order()
        problems = free_order_problems(order, confirm)
        would_send = {
            "isShareDataAccepted": bool(confirm and confirm.share_data),
            "isEmailNotificationAccepted": bool(confirm and confirm.email_notifications),
            "isWithdrawalConsentAccepted": bool(confirm and confirm.accept_withdrawal_consent),
            "orderChecksum": "<redacted>",
        }
        if confirm is None:
            return FreeOrderResult(False, order, problems, None, would_send)
        if problems:
            raise LibError("refusing the free order: " + "; ".join(problems), "nothing was sent")
        variables = {**would_send, "orderChecksum": order.checksum}
        data = self._graphql.execute("processFreeOrder", PROCESS_FREE_ORDER, variables)
        raw = data.get("processFreeOrder")
        if not isinstance(raw, dict):
            raise LibError("processFreeOrder returned no order", "check your account's order list in a browser")
        summary = parse_summary(raw)
        if summary.total != ZERO:
            raise LibError(f"the placed order's total is {summary.total}, not zero", "check the order in a browser")
        return FreeOrderResult(True, order, (), summary, would_send)


def free_order_problems(order: Order, confirm: FreeOrderConfirmation | None) -> tuple[str, ...]:
    """Every reason `order` is not a free order, and (given `confirm`) every way the confirmation does not match.

    The unconditional ones come first; with no confirmation the result is the plan's list of problems, which is
    empty for a basket that would pass.
    """
    problems: list[str] = []
    if not order.items:
        problems.append("the basket is empty")
    if order.total != ZERO:
        problems.append(f"the server reports a total of {order.total} {order.currency}, not zero")
    if order.total_tax != ZERO:
        problems.append("the server reports tax on it")
    if order.total_shipping != ZERO:
        problems.append("the server reports a shipping charge")
    for item in order.items:
        if item.unit_price != ZERO or item.total != ZERO:
            problems.append(f"{item.description!r} is not free ({item.unit_price} {item.currency})")
        if item.is_physical:
            problems.append(f"{item.description!r} is a print item that ships")
    if confirm is not None:
        if confirm.expected_total != ZERO:
            problems.append("the confirmation expects a total other than zero")
        if not confirm.accept_withdrawal_consent:
            problems.append("the withdrawal consent is not accepted; the webstore requires it")
        shown = frozenset(item.description for item in order.items)
        if shown != confirm.items:
            extra = sorted(shown - confirm.items)
            missing = sorted(confirm.items - shown)
            problems.append(
                f"the basket holds {extra or 'nothing extra'} and lacks {missing or 'nothing'} "
                "against the confirmation"
            )
    return tuple(problems)
