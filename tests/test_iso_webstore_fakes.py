"""Fakes and invented fixtures for the webstore tests. Real response SHAPES, invented values; no network."""

from __future__ import annotations

import base64
import contextlib
import io
import json
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from primarysource.iso.webstore import HttpRequest, HttpResponse, WebstoreSession

BASE = "https://www.iso.org"
SECRET_PASSPHRASE = "pass-phrase-for-tests-only"  # noqa: S105
SECRET_NAME = "tester@example.invalid"  # noqa: S105
SESSION_COOKIE = "cookie-value-for-tests-only"
FAR_FUTURE = 4102444800  # 2100-01-01


def reply(status: int = 200, body: bytes | str = b"", url: str = "", **headers: str) -> HttpResponse:
    data = body.encode() if isinstance(body, str) else body
    return HttpResponse(status, {k.replace("_", "-").lower(): v for k, v in headers.items()}, data, url)


def json_reply(payload: Any, status: int = 200) -> HttpResponse:
    return reply(status, json.dumps(payload), "", content_type="application/json")


class FakeStream:
    def __init__(self, status: int, body: bytes, headers: Mapping[str, str]) -> None:
        self.status = status
        self._body = io.BytesIO(body)
        self._headers = {k.lower(): v for k, v in headers.items()}

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def read(self, size: int) -> bytes:
        return self._body.read(size)


class FakeTransport:
    """Answers each request from `handler`. Records every request; holds a cookie dict."""

    def __init__(
        self,
        handler: Callable[[HttpRequest], HttpResponse],
        stream_handler: Callable[[HttpRequest], FakeStream] | None = None,
    ) -> None:
        self.handler = handler
        self.stream_handler = stream_handler
        self.requests: list[HttpRequest] = []
        self._cookies: dict[str, str] = {}

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        response = self.handler(request)
        return HttpResponse(response.status, response.headers, response.body, request.url)

    @contextlib.contextmanager
    def stream(self, request: HttpRequest) -> Iterator[FakeStream]:
        self.requests.append(request)
        assert self.stream_handler is not None
        yield self.stream_handler(request)

    def cookies(self) -> dict[str, str]:
        return dict(self._cookies)

    def set_cookies(self, cookies: Mapping[str, str]) -> None:
        self._cookies.update(cookies)

    def calls(self, method: str, fragment: str) -> list[HttpRequest]:
        return [r for r in self.requests if r.method == method and fragment in r.url]


def make_session(
    handler: Callable[[HttpRequest], HttpResponse],
    stream_handler: Callable[[HttpRequest], FakeStream] | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[WebstoreSession, FakeTransport, list[float]]:
    """A session over a fake transport with an instant clock; the third value records the sleeps requested."""
    transport = FakeTransport(handler, stream_handler)
    sleeps: list[float] = []
    now = [0.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    session = WebstoreSession(transport, environ=environ or {}, clock=lambda: now[0], sleep=sleep)
    return session, transport, sleeps


# --- invented pages and payloads ---------------------------------------------------------------------------------


def secured_key(valid_until: int = FAR_FUTURE) -> str:
    raw = f"deadbeefdeadbeef&validUntil={valid_until}&restrictIndices=TEST_index_en"
    return base64.b64encode(raw.encode()).decode()


def store_page(valid_until: int = FAR_FUTURE) -> str:
    return (
        "<html><head><title>Store</title></head><body><script>\n"
        "algolia = { settings: { appID: 'TESTAPP01', apiKey: '" + secured_key(valid_until) + "', "
        "index : { name: 'TEST_index_en' }, autocompleteDebounceTime : 1000 }, instantSearch: undefined };\n"
        "</script></body></html>"
    )


def login_page(action: str = "https://idp.iso.org/realms/test/login-actions/authenticate?session_code=abc") -> str:
    return (
        '<html><body><form id="login" onsubmit="login.disabled = true; return true;" '
        f'action="{action.replace("&", "&amp;")}" method="post">'
        '<input id="username" name="username" type="text" />'
        '<input id="password" name="password" type="password" />'
        '<input type="hidden" id="id-hidden-input" name="credentialId" />'
        '<input name="login" id="kc-login" type="submit" value="Sign In" /></form></body></html>'
    )


def item(description: str, *, unit: float = 0.0, fmt: str = "PDF", media: str = "Electronic") -> dict[str, Any]:
    return {
        "description": description,
        "language": "en",
        "format": fmt,
        "editionId": "e1",
        "edition": None,
        "paymentFrequency": "NA",
        "listPrice": unit,
        "unitPrice": unit,
        "currency": "CHF",
        "quantity": 1,
        "total": unit,
        "licenses": None,
        "follow": False,
        "followable": False,
        "media": media,
        "appliedDiscount": 0.0,
        "quantityDiscount": 0.0,
        "orderSizeDiscount": 0.0,
        "discretionaryDiscount": 0.0,
        "isShippingChargeLineItem": False,
        "itemId": {
            "priceBookId": "p",
            "ratePlanId": "r",
            "formatId": "f",
            "editionId": "e",
            "instanceId": None,
            "locked": False,
        },
        "lockedForUser": False,
    }


def order(items: list[dict[str, Any]], total: float = 0.0, tax: float = 0.0, shipping: float = 0.0) -> dict[str, Any]:
    return {
        "orderStatus": "Initial",
        "currency": "CHF",
        "total": total,
        "totalTax": tax,
        "totalShippingCharge": shipping,
        "items": items,
        "checksum": "c" * 64,
    }


def summary(total: float = 0.0) -> dict[str, Any]:
    return {
        "orderNumber": "O-1",
        "accountId": "A-1",
        "paymentMethodType": "None",
        "orderStatus": "Complete",
        "purchaseOrderNumber": None,
        "total": total,
        "totalTax": 0.0,
        "totalShippingCharge": 0.0,
        "currency": "CHF",
        "items": [
            {
                "productName": "ISO/IEC 99999",
                "productType": "Standard",
                "productCode": "iso:std:iso-iec:99999:-1",
                "language": "en",
                "format": "PDF",
                "media": "Electronic",
                "editionYear": "2031",
                "edition": "1",
                "quantity": 1,
                "licenses": "1",
                "unitPrice": 0.0,
                "description": "ISO/IEC 99999",
                "requiresShipping": False,
            }
        ],
        "messages": ["done"],
    }
