"""The guarded cart and the free order. Nothing here changes the store unless handed a `Confirmation`.

Observed in the capture (one free item, ISO/IEC 7498-4:1989, ordered by a logged-in owner):

1. `GET /en/publication/<id>`: HTML with `<form id="product_addtocart_form" action=".../checkout/cart/add/uenc/
   <b64>/product/<productId>/">`: hidden `product`, `selected_configurable_option`, `related_product`, `item`,
   `form_key`, and three selects, `options[publication_language]`, `options[publication_format]`,
   `options[license_price]` (the number of users: `1`, `2 - 3`, `4 - 5`, ...), each option an id and a label. The
   head carries `og:title` (the designation) and `product:price:amount` / `product:price:currency`.
2. `POST` that action, `multipart/form-data`: the fields above plus `qty`. Answer 302 to the publication page.
3. `GET /en/rest/en/V1/carts/mine/totals`: `grand_total`, `subtotal`, `tax_amount`, `shipping_amount`,
   `base_currency_code`, `items_qty`, `items[]`. A free item totals 0 in every field.
4. `POST /en/rest/en/V1/carts/mine/set-payment-information` `{cartId, paymentMethod: {method: "free"}}`: `true`.
5. `POST /en/rest/en/V1/carts/mine/billing-address` `{cartId, address: {...}}`: the address id as a string.
6. `POST /en/rest/en/V1/carts/mine/payment-information` `{cartId, billingAddress, paymentMethod: {method: "free",
   po_number, additional_data, extension_attributes: {agreement_ids: ["1"]}}}`: the new order id as an integer.
   The payment methods offered were `free` ("No payment / Corporate account"), `datatrans_credit_debit_cards`,
   `datatrans_paypal` and `banktransfer`; only `free` is ever used here.

The safety rules, in code:

- every function that POSTs takes a `Confirmation` and is a dry run (it returns a `Plan`, makes no state-changing
  request) when given none;
- a `Confirmation` names the item (its designation, matched against the page) and the total expected;
- `order_free` refuses unless the confirmation's expected total is zero AND the server's own `grand_total` is zero,
  and unless the cart holds that one item and nothing else; placing it also needs `accept_terms=True`, because the
  store's own order carries the terms agreement id;
- nothing is removed from a cart (the removal call is not in the capture), so `add_to_cart` refuses to start if the
  cart already holds anything else.

Account creation, address-book and payment-method mutations are not implemented (docs/iec-webstore.md).
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any

from primarysource.errors import LibError
from primarysource.iec.webstore.session import IecSession
from primarysource.iec.webstore.transport import HttpRequest

__all__ = [
    "BillingAddress",
    "Confirmation",
    "ItemChoice",
    "OrderResult",
    "Plan",
    "PublicationPage",
    "Shop",
    "parse_publication_page",
]

TOLERANCE = 0.005


@dataclass(frozen=True, slots=True)
class Confirmation:
    """The caller's explicit yes: this item, at this total, in this currency."""

    reference: str
    expected_total: float
    currency: str = "CHF"
    accept_terms: bool = False


@dataclass(frozen=True, slots=True)
class ItemChoice:
    """The three selects of the add-to-cart form, by their labels."""

    language: str = "English"
    format: str = "Electronic"
    users: str = "1"


@dataclass(frozen=True, slots=True)
class BillingAddress:
    """The owner's billing address, supplied by the caller at run time. Every field is hidden from `repr`."""

    first_name: str = field(repr=False)
    last_name: str = field(repr=False)
    street: tuple[str, ...] = field(repr=False)
    city: str = field(repr=False)
    postcode: str = field(repr=False)
    country_id: str = field(repr=False)
    telephone: str = field(repr=False)
    region: str = field(default="", repr=False)
    region_id: str = field(default="", repr=False)
    region_code: str = field(default="", repr=False)

    def __repr__(self) -> str:
        return "BillingAddress(<redacted>)"

    def payload(self) -> dict[str, Any]:
        return {
            "countryId": self.country_id,
            "regionId": self.region_id,
            "regionCode": self.region_code,
            "region": self.region,
            "street": list(self.street),
            "telephone": self.telephone,
            "postcode": self.postcode,
            "city": self.city,
            "firstname": self.first_name,
            "lastname": self.last_name,
            "saveInAddressBook": 0,
        }


@dataclass(frozen=True, slots=True)
class Plan:
    """What a call would do, returned instead of doing it."""

    action: str
    reference: str
    total: float | None
    currency: str
    steps: tuple[str, ...]
    executed: bool = False


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: str
    reference: str
    total: float
    currency: str
    executed: bool = True


# --- the publication page ----------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicationPage:
    reference: str
    product_id: str
    price: float | None
    currency: str
    action_url: str
    fields: Mapping[str, str] = field(repr=False)
    """The hidden inputs, `form_key` among them; never printed."""
    options: Mapping[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    """Select name -> `(option id, label)` pairs, the placeholder left out."""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.action = ""
        self.fields: dict[str, str] = {}
        self.options: dict[str, list[tuple[str, str]]] = {}
        self._in_form = False
        self._select: str | None = None
        self._option: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta" and a.get("property"):
            self.meta[a["property"]] = a.get("content", "")
        elif tag == "form" and a.get("id") == "product_addtocart_form":
            self._in_form = True
            self.action = a.get("action", "")
        elif not self._in_form:
            return
        elif tag == "input" and a.get("name"):
            self.fields[a["name"]] = a.get("value", "")
        elif tag == "select":
            self._select = a.get("name", "")
            self.options[self._select] = []
        elif tag == "option" and self._select is not None:
            self._option = a.get("value", "")
            self._label = []

    def handle_data(self, data: str) -> None:
        if self._option is not None:
            self._label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._select is not None and self._option is not None:
            if self._option:
                self.options[self._select].append((self._option, " ".join("".join(self._label).split())))
            self._option = None
        elif tag == "select":
            self._select = None
        elif tag == "form":
            self._in_form = False


def parse_publication_page(html: str) -> PublicationPage:
    parser = _PageParser()
    parser.feed(html)
    match = re.search(r"/product/(\d+)/?$", parser.action)
    if not parser.action or match is None:
        raise LibError(
            "no add-to-cart form on this page",
            "check the publication id; the item may not be for sale here (see docs/iec-webstore.md)",
        )
    reference = unescape(parser.meta.get("og:title", "")).strip()
    amount = parser.meta.get("product:price:amount")
    try:
        price = float(amount) if amount else None
    except ValueError:
        price = None
    return PublicationPage(
        reference,
        match.group(1),
        price,
        parser.meta.get("product:price:currency", ""),
        parser.action,
        dict(parser.fields),
        {name: tuple(values) for name, values in parser.options.items()},
    )


def multipart(fields: list[tuple[str, str]]) -> tuple[bytes, str]:
    """A `multipart/form-data` body, as the page's own form submits it, and its Content-Type."""
    boundary = "----primarysource" + secrets.token_hex(12)
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n' for name, value in fields
    ]
    return ("".join(parts) + f"--{boundary}--\r\n").encode("utf-8"), f"multipart/form-data; boundary={boundary}"


def _same(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def _pick(page: PublicationPage, select: str, label: str) -> str:
    for value, text in page.options.get(f"options[{select}]", ()):
        if _same(text, label):
            return value
    known = ", ".join(text for _, text in page.options.get(f"options[{select}]", ())) or "none"
    raise LibError(f"{page.reference}: no {select} option {label!r} (offered: {known})", f"choose one of: {known}")


class Shop:
    def __init__(self, session: IecSession) -> None:
        self._session = session

    def read_publication(self, publication_id: int) -> PublicationPage:
        """Read-only: the publication page, parsed."""
        response = self._session.get(f"publication/{int(publication_id)}")
        if response.status != 200:
            raise LibError(f"the store answered HTTP {response.status} for the publication page", "check the id")
        return parse_publication_page(response.text())

    # --- add to cart ----------------------------------------------------------------------------------------------

    def add_to_cart(
        self, publication_id: int, choice: ItemChoice | None = None, confirm: Confirmation | None = None
    ) -> Plan:
        choice = choice or ItemChoice()
        page = self.read_publication(publication_id)
        language = _pick(page, "publication_language", choice.language)
        fmt = _pick(page, "publication_format", choice.format)
        users = _pick(page, "license_price", choice.users)
        steps = (
            f"GET publication/{int(publication_id)} (done)",
            "GET customer/section/load/ (cart must be empty or hold only this item)",
            f"POST {page.action_url.split('/uenc/')[0]}/... (multipart: product, options, qty=1)",
        )
        total = page.price
        plan = Plan("add-to-cart", page.reference, total, page.currency, steps)
        if confirm is None:
            return plan
        self._check_item(confirm, page.reference, total, page.currency)
        cart = self._session.cart()
        if any(item.product_id != page.product_id for item in cart.items):
            raise LibError(
                "the cart already holds another item",
                "empty the cart in the browser first: this client never removes anything",
            )
        fields = [
            ("product", page.fields.get("product", page.product_id)),
            ("selected_configurable_option", ""),
            ("related_product", ""),
            ("item", page.fields.get("item", page.product_id)),
            ("form_key", self._session.form_key()),
            ("options[publication_language]", language),
            ("options[publication_format]", fmt),
            ("options[license_price]", users),
            ("qty", "1"),
        ]
        body, content_type = multipart(fields)
        headers = {"Content-Type": content_type, "Accept": "text/html"}
        response = self._session.transport.send(HttpRequest("POST", page.action_url, headers, body))
        if response.status not in (200, 302):
            raise LibError(
                f"the store answered HTTP {response.status} to the cart-add", "look at the cart in a browser"
            )
        after = self._session.cart()
        if not any(item.product_id == page.product_id for item in after.items):
            raise LibError("the item is not in the cart after the add", "look at the cart in a browser")
        return Plan("add-to-cart", page.reference, total, page.currency, steps, executed=True)

    # --- free order -----------------------------------------------------------------------------------------------

    def _check_item(self, confirm: Confirmation, reference: str, total: float | None, currency: str) -> None:
        if not _same(confirm.reference, reference):
            raise LibError(
                f"the confirmation names {confirm.reference!r}, the page is {reference!r}", "confirm the right item"
            )
        if total is None or abs(total - confirm.expected_total) > TOLERANCE:
            raise LibError(
                f"the confirmation expects a total of {confirm.expected_total:g}, the store shows {total}",
                "nothing was changed; confirm the price the store shows",
            )
        if currency and confirm.currency and currency != confirm.currency:
            raise LibError(f"the store prices in {currency}, not {confirm.currency}", "nothing was changed")

    def totals(self) -> dict[str, Any]:
        response = self._session.get("rest/en/V1/carts/mine/totals", self._session.ajax_headers(json_body=True))
        if response.status != 200:
            raise LibError(f"the store answered HTTP {response.status} for the cart totals", "log in first")
        data = response.json()
        if not isinstance(data, dict) or "grand_total" not in data:
            raise LibError("the cart totals have an unexpected shape", "the site may have changed; see docs")
        return data

    def order_free(
        self, billing: BillingAddress, confirm: Confirmation | None = None, agreement_ids: tuple[str, ...] = ("1",)
    ) -> Plan | OrderResult:
        """Place the order for a cart whose server-reported grand total is zero. Refuses otherwise, dry run or not."""
        cart = self._session.cart()
        if len(cart.items) != 1 or not cart.cart_id:
            raise LibError(
                f"the cart holds {len(cart.items)} items; a free order needs exactly one", "nothing was changed"
            )
        totals = self.totals()
        grand = float(totals["grand_total"])
        currency = str(totals.get("quote_currency_code") or totals.get("base_currency_code") or "")
        if abs(grand) > TOLERANCE:
            raise LibError(
                f"the server reports a grand total of {grand:g} {currency}, not zero",
                "this client only places free orders; nothing was changed",
            )
        item = cart.items[0]
        steps = (
            "GET customer/section/load/ (done)",
            "GET rest/en/V1/carts/mine/totals (done: grand total 0)",
            "POST rest/en/V1/carts/mine/set-payment-information (method free)",
            "POST rest/en/V1/carts/mine/billing-address",
            "POST rest/en/V1/carts/mine/payment-information (method free, terms accepted)",
        )
        plan = Plan("order-free", item.name, 0.0, currency, steps)
        if confirm is None:
            return plan
        if abs(confirm.expected_total) > TOLERANCE:
            raise LibError("a free order is confirmed at a total of 0", "this client never places a paid order")
        if not confirm.accept_terms:
            raise LibError(
                "placing the order accepts the store's terms",
                "pass accept_terms=True only if the owner has read and accepted them",
            )
        if confirm.reference.casefold() not in item.name.casefold() and not _same(confirm.reference, item.name):
            raise LibError(
                f"the cart item {item.name!r} is not the confirmed {confirm.reference!r}", "nothing was changed"
            )
        cart_id = cart.cart_id
        method = {"method": "free"}
        self._post(
            "rest/en/V1/carts/mine/set-payment-information",
            {"cartId": cart_id, "paymentMethod": method},
            "payment method",
        )
        self._post(
            "rest/en/V1/carts/mine/billing-address",
            {"cartId": cart_id, "address": billing.payload()},
            "billing address",
        )
        order = self._post(
            "rest/en/V1/carts/mine/payment-information",
            {
                "cartId": cart_id,
                "billingAddress": billing.payload(),
                "paymentMethod": {
                    "method": "free",
                    "po_number": None,
                    "additional_data": None,
                    "extension_attributes": {"agreement_ids": list(agreement_ids)},
                },
            },
            "order",
        )
        if isinstance(order, bool) or not isinstance(order, int | str) or not str(order).isdigit():
            raise LibError("the store did not answer an order id", "look at the order history in a browser")
        return OrderResult(str(order), item.name, 0.0, currency)

    def _post(self, path: str, payload: Any, what: str) -> Any:
        response = self._session.post_json(path, payload)
        if response.status != 200:
            raise LibError(
                f"the store answered HTTP {response.status} setting the {what}", "look at the cart in a browser"
            )
        try:
            return json.loads(response.body)
        except ValueError:
            return None
