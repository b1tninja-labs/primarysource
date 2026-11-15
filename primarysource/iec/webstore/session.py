"""The Magento customer session: `form_key`, login, the private-content sections.

Observed in the capture:

- the storefront's own JavaScript makes the `form_key` cookie itself (16 characters of `0-9a-zA-Z`) when it is
  missing, and sends it as the `formKey` field of the login and as the `form_key` field of the cart-add;
- login is `POST /en/customer/ajax/login/`, a JSON body `{username, password, formKey}` (plus
  `g-recaptcha-response` when the page has a reCAPTCHA field), headers `Content-Type: application/json` and
  `X-Requested-With: XMLHttpRequest`; the answer is JSON with `errors` and `message` on failure. The capture
  holds no login POST (it was an account-creation session), so the success answer is unobserved;
- afterwards the session cookie is the login. There is no bearer token: the REST calls under `/en/rest/` carry
  the same cookie plus `X-Requested-With`;
- `GET /en/customer/section/load/?sections=` answers every private-content section; `customer` holds the name
  fields only when logged in, and `cart` holds the cart's id, count, subtotal and items.

A CAPTCHA is never solved or bypassed here: if the store asks for one, `login` stops and says so.
"""

from __future__ import annotations

import json
import secrets
import string
from dataclasses import dataclass
from typing import Any

from primarysource.errors import LibError
from primarysource.iec.webstore._secret import Credentials
from primarysource.iec.webstore.transport import HttpRequest, HttpResponse, Transport

__all__ = ["BASE", "CartItem", "CartSnapshot", "IecSession"]

BASE = "https://webstore.iec.ch/en/"
_ALPHABET = string.ascii_letters + string.digits


@dataclass(frozen=True, slots=True)
class CartItem:
    item_id: str
    product_id: str
    sku: str
    name: str
    price: float
    options: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CartSnapshot:
    cart_id: str
    count: int
    items: tuple[CartItem, ...]


class IecSession:
    def __init__(self, transport: Transport, base: str = BASE) -> None:
        self.transport = transport
        self.base = base

    # --- requests -----------------------------------------------------------------------------------------------

    def ajax_headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def get(self, path: str, headers: dict[str, str] | None = None) -> HttpResponse:
        return self.transport.send(HttpRequest("GET", self.base + path, headers or {}))

    def post_json(self, path: str, payload: Any) -> HttpResponse:
        body = json.dumps(payload).encode("utf-8")
        return self.transport.send(HttpRequest("POST", self.base + path, self.ajax_headers(json_body=True), body))

    # --- form_key and login -------------------------------------------------------------------------------------

    def form_key(self) -> str:
        """The `form_key` cookie, made the way the storefront's JavaScript makes it if the jar has none."""
        value = self.transport.cookie("form_key")
        if not value:
            value = "".join(secrets.choice(_ALPHABET) for _ in range(16))
            self.transport.set_cookie("form_key", value)
        return value

    def login(self, credentials: Credentials) -> None:
        """Log in, then check the sections say so. Raises `LibError` (without the credentials in it) otherwise."""
        payload = {
            "username": credentials.username.reveal(),
            "password": credentials.password.reveal(),
            "formKey": self.form_key(),
        }
        response = self.post_json("customer/ajax/login/", payload)
        if response.status != 200:
            raise LibError(
                f"the store refused the login (HTTP {response.status})",
                "check the credentials in the environment; if the store wants a CAPTCHA, log in in a browser and "
                "pass the session with PRIMARYSOURCE_IEC_SESSION_FILE",
            )
        try:
            answer = response.json()
        except LibError:
            answer = {}
        if isinstance(answer, dict) and answer.get("errors"):
            raise LibError(
                "the store did not accept the login",
                "check the credentials in the environment (the store's message is not repeated here)",
            )
        if not self.is_logged_in():
            raise LibError(
                "the login answered, but the session is not logged in",
                "the store may need a CAPTCHA or another step; log in in a browser instead",
            )

    # --- sections -----------------------------------------------------------------------------------------------

    def sections(self) -> dict[str, Any]:
        response = self.get("customer/section/load/?sections=", self.ajax_headers())
        if response.status != 200:
            raise LibError(f"the store answered HTTP {response.status} to the section load", "try again later")
        data = response.json()
        if not isinstance(data, dict):
            raise LibError("the section load is not an object", "the site may have changed; see docs/iec-webstore.md")
        return data

    def is_logged_in(self) -> bool:
        customer = self.sections().get("customer")
        return isinstance(customer, dict) and bool(customer.get("firstname") or customer.get("fullname"))

    def cart(self) -> CartSnapshot:
        cart = self.sections().get("cart") or {}
        items = tuple(
            CartItem(
                str(item.get("item_id", "")),
                str(item.get("product_id", "")),
                str(item.get("product_sku", "")),
                str(item.get("product_name", "")),
                float(item.get("product_price_value") or 0),
                tuple((str(o.get("label", "")), str(o.get("value", ""))) for o in item.get("options") or ()),
            )
            for item in cart.get("items") or ()
        )
        return CartSnapshot(str(cart.get("cartId") or ""), int(cart.get("summary_count") or 0), items)
