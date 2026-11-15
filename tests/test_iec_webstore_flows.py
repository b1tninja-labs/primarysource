"""iec webstore: login, the guarded cart and free order, orders and the owned download. Fake transport only.

Every state-changing call is checked two ways: it does nothing without a `Confirmation`, and it refuses a
confirmation that does not match what the (fake) server says. Names, ids, prices and the address are invented.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from test_iec_webstore import FakeStream, FakeTransport

from primarysource.errors import LibError
from primarysource.iec.webstore import (
    BillingAddress,
    Confirmation,
    Credentials,
    HttpRequest,
    HttpResponse,
    IecSession,
    ItemChoice,
    OrderClient,
    OrderResult,
    Plan,
    Shop,
)
from primarysource.iec.webstore.cart import multipart, parse_publication_page
from primarysource.iec.webstore.orders import parse_order_ids, parse_order_view

BASE = "https://webstore.iec.ch/en/"
REF = "XYZ 1:2099"
DOWNLOAD_URL = (
    "https://storage-watermark-prd-example.s3.eu-west-1.amazonaws.com/a/b/XYZ-1.zip?X-Amz-Signature=invented"
)

PAGE = f"""<html><head><title>{REF} | IEC</title>
<meta property="og:title" content="XYZ&#x20;1&#x3A;2099"/>
<meta property="product:price:amount" content="0"/><meta property="product:price:currency" content="CHF"/>
</head><body>
<form method="post" action="https://webstore.iec.ch/en/checkout/cart/add/uenc/QUJD/product/900/"
 id="product_addtocart_form" enctype="multipart/form-data">
<input name="product" type="hidden" value="900"/><input name="selected_configurable_option" type="hidden" value=""/>
<input name="related_product" type="hidden" value=""/><input name="item" type="hidden" value="900"/>
<input name="form_key" type="hidden" value="PAGEKEY"/>
<select name="options[publication_language]"><option value="">-- Please select --</option>
<option value="13">English</option><option value="16">French</option></select>
<select name="options[publication_format]"><option value="">-- Please select --</option>
<option value="37">Electronic</option><option value="46">Hardcopy</option></select>
<select name="options[license_price]"><option value="">-- Please select --</option>
<option value="2">1</option><option value="3">2 - 3</option></select>
</form></body></html>"""

PAGE_PAID = PAGE.replace('content="0"/><meta', 'content="405"/><meta')


def cart_section(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "customer": {"firstname": "Someone"},
        "cart": {"cartId": "77", "summary_count": len(items), "items": items},
    }


def cart_item(name: str = REF, product_id: str = "900") -> dict[str, Any]:
    return {
        "item_id": "5",
        "product_id": product_id,
        "product_sku": "SKU",
        "product_name": name,
        "product_price_value": 0,
        "options": [{"label": "Language", "value": "English"}],
    }


def totals(grand: float) -> dict[str, Any]:
    return {"grand_total": grand, "subtotal": grand, "quote_currency_code": "CHF", "items_qty": 1}


def address() -> BillingAddress:
    return BillingAddress("Invented", "Person", ("1 Nowhere Road",), "Nowhere", "00000", "CH", "000")


def session_for(transport: FakeTransport) -> IecSession:
    return IecSession(transport)


# --- login ---------------------------------------------------------------------------------------------------------


def test_login_makes_a_form_key_and_posts_json_without_leaking_credentials() -> None:
    transport = FakeTransport()
    transport.json_route("POST", BASE + "customer/ajax/login/", {"errors": False, "message": "ok"})
    transport.json_route("GET", BASE + "customer/section/load/", cart_section([]))
    session = session_for(transport)
    session.login(Credentials.from_env({"PRIMARYSOURCE_IEC_USERNAME": "who", "PRIMARYSOURCE_IEC_PASSWORD": "pw-x"}))
    key = transport.cookies["form_key"]
    assert len(key) == 16 and key.isalnum()
    post = transport.posts()[0]
    assert post.url == BASE + "customer/ajax/login/"
    assert json.loads(post.body or b"") == {"username": "who", "password": "pw-x", "formKey": key}
    assert post.headers["X-Requested-With"] == "XMLHttpRequest" and post.headers["Content-Type"] == "application/json"
    assert session.form_key() == key  # reused, not remade


def test_login_failures_name_a_remedy_and_never_echo_the_credentials() -> None:
    creds = Credentials.from_env(
        {"PRIMARYSOURCE_IEC_USERNAME": "who@example.org", "PRIMARYSOURCE_IEC_PASSWORD": "pw-x"}
    )
    refused = FakeTransport()
    refused.json_route("POST", BASE + "customer/ajax/login/", {"errors": True, "message": "bad who@example.org"})
    with pytest.raises(LibError) as error:
        session_for(refused).login(creds)
    text = error.value.as_text()
    assert "who@example.org" not in text and "pw-x" not in text and error.value.hint

    blocked = FakeTransport()
    blocked.json_route("POST", BASE + "customer/ajax/login/", {}, status=403)
    with pytest.raises(LibError, match="403"):
        session_for(blocked).login(creds)

    silent = FakeTransport()  # login answers ok but the session is still anonymous
    silent.json_route("POST", BASE + "customer/ajax/login/", {"errors": False})
    silent.json_route("GET", BASE + "customer/section/load/", {"customer": {"data_id": 1}, "cart": {}})
    with pytest.raises(LibError, match="not logged in"):
        session_for(silent).login(creds)


# --- the publication page and the cart -----------------------------------------------------------------------------


def test_publication_page_parses_form_options_and_price() -> None:
    page = parse_publication_page(PAGE)
    assert (page.reference, page.product_id, page.price, page.currency) == (REF, "900", 0.0, "CHF")
    assert page.options["options[publication_language]"] == (("13", "English"), ("16", "French"))
    assert "PAGEKEY" not in repr(page)
    with pytest.raises(LibError):
        parse_publication_page("<html></html>")


def shop_for(page: str = PAGE, cart: list[dict[str, Any]] | None = None) -> tuple[Shop, FakeTransport]:
    transport = FakeTransport()
    transport.route("GET", BASE + "publication/1001", HttpResponse(200, {}, page.encode()))
    state = {"items": list(cart or [])}
    transport.route(
        "GET",
        BASE + "customer/section/load/",
        lambda _r: HttpResponse(200, {}, json.dumps(cart_section(state["items"])).encode()),
    )

    def add(_request: HttpRequest) -> HttpResponse:
        state["items"] = [cart_item()]
        return HttpResponse(302, {"location": BASE + "publication/1001"}, b"")

    transport.route("POST", BASE + "checkout/cart/add/", add)
    return Shop(session_for(transport)), transport


def test_add_to_cart_is_a_dry_run_without_a_confirmation() -> None:
    shop, transport = shop_for()
    plan = shop.add_to_cart(1001)
    assert isinstance(plan, Plan) and not plan.executed and plan.reference == REF
    assert transport.posts() == []


def test_add_to_cart_posts_the_observed_multipart_only_when_confirmed() -> None:
    shop, transport = shop_for()
    plan = shop.add_to_cart(1001, ItemChoice("English", "Electronic", "1"), Confirmation(REF, 0.0))
    assert plan.executed
    (post,) = transport.posts()
    assert post.url == "https://webstore.iec.ch/en/checkout/cart/add/uenc/QUJD/product/900/"
    body = (post.body or b"").decode()
    for field in ("product", "item", "form_key", "options[publication_language]", "options[license_price]", "qty"):
        assert f'name="{field}"' in body
    assert 'name="options[publication_language]"\r\n\r\n13\r\n' in body and 'name="qty"\r\n\r\n1\r\n' in body
    assert post.headers["Content-Type"].startswith("multipart/form-data; boundary=")


@pytest.mark.parametrize(
    ("confirm", "choice"),
    [
        (Confirmation("OTHER 9:2099", 0.0), ItemChoice()),
        (Confirmation(REF, 10.0), ItemChoice()),
        (Confirmation(REF, 0.0, currency="EUR"), ItemChoice()),
        (Confirmation(REF, 0.0), ItemChoice(language="Klingon")),
    ],
)
def test_add_to_cart_refuses_a_mismatched_confirmation_before_any_post(
    confirm: Confirmation, choice: ItemChoice
) -> None:
    shop, transport = shop_for()
    with pytest.raises(LibError):
        shop.add_to_cart(1001, choice, confirm)
    assert transport.posts() == []


def test_add_to_cart_refuses_a_cart_that_holds_something_else() -> None:
    shop, transport = shop_for(cart=[cart_item("OTHER 1", product_id="123")])
    with pytest.raises(LibError, match="another item"):
        shop.add_to_cart(1001, confirm=Confirmation(REF, 0.0))
    assert transport.posts() == []


def test_multipart_is_well_formed() -> None:
    body, content_type = multipart([("a", "1"), ("b", "")])
    boundary = content_type.split("boundary=")[1]
    assert body.decode().endswith(f"--{boundary}--\r\n") and body.decode().count(f"--{boundary}") == 3


# --- the free order -------------------------------------------------------------------------------------------------


def order_shop(grand: float = 0.0, items: list[dict[str, Any]] | None = None) -> tuple[Shop, FakeTransport]:
    transport = FakeTransport()
    transport.json_route(
        "GET", BASE + "customer/section/load/", cart_section([cart_item()] if items is None else items)
    )
    transport.json_route("GET", BASE + "rest/en/V1/carts/mine/totals", totals(grand))
    transport.json_route("POST", BASE + "rest/en/V1/carts/mine/set-payment-information", True)
    transport.json_route("POST", BASE + "rest/en/V1/carts/mine/billing-address", "12345")
    transport.json_route("POST", BASE + "rest/en/V1/carts/mine/payment-information", 4242)
    return Shop(session_for(transport)), transport


def test_free_order_is_a_dry_run_without_a_confirmation() -> None:
    shop, transport = order_shop()
    plan = shop.order_free(address())
    assert isinstance(plan, Plan) and not plan.executed and plan.total == 0.0
    assert transport.posts() == []


def test_free_order_places_exactly_the_three_observed_posts() -> None:
    shop, transport = order_shop()
    result = shop.order_free(address(), Confirmation(REF, 0.0, accept_terms=True))
    assert isinstance(result, OrderResult) and result.order_id == "4242" and result.total == 0.0
    assert [r.url.removeprefix(BASE) for r in transport.posts()] == [
        "rest/en/V1/carts/mine/set-payment-information",
        "rest/en/V1/carts/mine/billing-address",
        "rest/en/V1/carts/mine/payment-information",
    ]
    final = json.loads(transport.posts()[2].body or b"")
    assert final["cartId"] == "77" and final["paymentMethod"]["method"] == "free"
    assert final["paymentMethod"]["extension_attributes"] == {"agreement_ids": ["1"]}
    assert set(final["billingAddress"]) >= {"countryId", "street", "city", "postcode", "saveInAddressBook"}


def test_free_order_refuses_a_nonzero_server_total_even_as_a_dry_run() -> None:
    for confirm in (None, Confirmation(REF, 0.0, accept_terms=True), Confirmation(REF, 405.0, accept_terms=True)):
        shop, transport = order_shop(grand=405.0)
        with pytest.raises(LibError, match="not zero"):
            shop.order_free(address(), confirm)
        assert transport.posts() == []


@pytest.mark.parametrize(
    "confirm",
    [
        Confirmation(REF, 0.0),  # terms not accepted
        Confirmation(REF, 1.0, accept_terms=True),  # a free order is confirmed at zero only
        Confirmation("OTHER 9:2099", 0.0, accept_terms=True),  # not the item in the cart
    ],
)
def test_free_order_refuses_an_incomplete_or_mismatched_confirmation(confirm: Confirmation) -> None:
    shop, transport = order_shop()
    with pytest.raises(LibError):
        shop.order_free(address(), confirm)
    assert transport.posts() == []


def test_free_order_refuses_an_empty_or_crowded_cart() -> None:
    for items in ([], [cart_item(), cart_item("OTHER 1", "2")]):
        shop, transport = order_shop(items=items)
        with pytest.raises(LibError, match="exactly one"):
            shop.order_free(address(), Confirmation(REF, 0.0, accept_terms=True))
        assert transport.posts() == []


def test_the_address_is_never_printed() -> None:
    assert "Nowhere" not in repr(address()) and "Invented" not in repr(address())


# --- orders and downloads -------------------------------------------------------------------------------------------

ORDER_PAGE = f"""<html><body><span>Status:&nbsp; </span> Complete
<div x-data="orderDownloadDropdown(4242)"> <a>Order</a> </div>
<div class="order-details-items ordered"><div class="order-items"><div class="table-responsive">
<div class="table-head-item item-desktop"> Product reference </div>
<div class="table-data-item item-title font-bold"> <!-- <a href="--><!--" target="_blank">--> {REF}</div>
<div class="table-data-item"> English</div><div class="table-data-item"> Electronic</div>
<div class="table-data-item lg:justify-center"> 1</div>
<div class="table-data-item download-desktop"> <div x-data="getStatus99(555)"><template></template></div>
<script> function getStatus99(orderItemId) {{ return {{}} }} </script> </div>
<div class="table-data-item lg:justify-end"> <span class="price">CHF 0.-</span> </div>
</div></div></div>
<div>Order information</div><div>Billing address Someone Else</div></body></html>"""


def test_order_page_parses_items_and_ignores_personal_blocks() -> None:
    view = parse_order_view(ORDER_PAGE)
    assert view.order_id == "4242" and view.complete
    (item,) = view.items
    assert (item.reference, item.language, item.format, item.quantity, item.item_id) == (
        REF,
        "English",
        "Electronic",
        1,
        "555",
    )
    assert item.price == "CHF 0.-"
    assert "Someone" not in repr(view)
    with pytest.raises(LibError):
        parse_order_view("<html></html>")
    assert parse_order_ids(
        '<a href="x/sales/order/view/order_id/7/">a</a><a href="/sales/order/view/order_id/7/">b</a>'
    ) == ("7",)


def status_body(status: str, downloadable: bool, url: str | None) -> HttpResponse:
    inner = json.dumps({"status": status, "is_downloadable": downloadable, "download_url": url})
    return HttpResponse(200, {}, json.dumps(inner).encode())  # double-encoded, as the store answers


def orders_for(*answers: HttpResponse) -> tuple[OrderClient, FakeTransport, list[float]]:
    transport = FakeTransport()
    queue = list(answers)
    transport.route(
        "GET",
        BASE + "rest/V1/publications/mine/download-status/",
        lambda _r: queue.pop(0) if len(queue) > 1 else queue[0],
    )
    transport.route("GET", BASE + "sales/order/view/order_id/4242/", HttpResponse(200, {}, ORDER_PAGE.encode()))
    history = f'<a href="{BASE}sales/order/view/order_id/4242/">order</a>'
    transport.route("GET", BASE + "sales/order/history/", HttpResponse(200, {}, history.encode()))
    return OrderClient(session_for(transport)), transport, []


def test_download_status_decodes_the_double_encoded_answer_and_hides_the_url() -> None:
    client, transport, _ = orders_for(status_body("COMPLETED", True, DOWNLOAD_URL))
    status = client.download_status(order_id="4242")
    assert status.is_downloadable and status.download_url is not None
    assert "X-Amz-Signature" not in repr(status) and status.download_url.reveal() == DOWNLOAD_URL
    assert transport.requests[0].url == BASE + "rest/V1/publications/mine/download-status/order/4242"
    client.download_status(item_id="555")
    assert transport.requests[1].url.endswith("/download-status/555")
    for kwargs in ({}, {"order_id": "1", "item_id": "2"}, {"order_id": "x"}):
        with pytest.raises(LibError):
            client.download_status(**kwargs)


def test_owned_lists_items_from_orders_with_one_request_per_order() -> None:
    client, transport, _ = orders_for(status_body("COMPLETED", True, DOWNLOAD_URL))
    owned = client.owned(max_orders=5)
    assert [(o, i.reference) for o, i in owned] == [("4242", REF)]
    assert len(transport.requests) == 2  # history page, then the one order it links


def test_download_waits_streams_to_part_then_replaces_and_hashes(tmp_path: Path) -> None:
    payload = b"invented archive bytes" * 100
    client, transport, _ = orders_for(
        status_body("PROCESSING", False, None), status_body("COMPLETED", True, DOWNLOAD_URL)
    )
    transport.streams[DOWNLOAD_URL] = FakeStream(200, payload, {"content-length": str(len(payload))})
    naps: list[float] = []
    result = client.download(tmp_path / "out", order_id="4242", sleep=naps.append)
    assert naps == [5.0]
    assert result.path.name == "XYZ-1.zip" and result.path.read_bytes() == payload
    assert (result.size, result.sha256) == (len(payload), hashlib.sha256(payload).hexdigest())
    assert not list((tmp_path / "out").glob("*.part"))
    with pytest.raises(LibError, match="already exists"):
        client.download(tmp_path / "out", order_id="4242", sleep=naps.append)


def test_download_gives_up_when_the_store_never_prepares_it(tmp_path: Path) -> None:
    client, _, _ = orders_for(status_body("PROCESSING", False, None))
    naps: list[float] = []
    with pytest.raises(LibError, match="not made the file available"):
        client.download(tmp_path, order_id="4242", sleep=naps.append, max_polls=3)
    assert len(naps) == 2


def test_download_leaves_no_part_file_on_a_short_body(tmp_path: Path) -> None:
    client, transport, _ = orders_for(status_body("COMPLETED", True, DOWNLOAD_URL))
    transport.streams[DOWNLOAD_URL] = FakeStream(200, b"short", {"content-length": "999"})
    with pytest.raises(LibError, match="999"):
        client.download(tmp_path, order_id="4242")
    assert list(tmp_path.iterdir()) == []


def test_download_refuses_other_hosts_and_repository_destinations(tmp_path: Path) -> None:
    client, transport, _ = orders_for(status_body("COMPLETED", True, "https://evil.example.org/x.zip"))
    with pytest.raises(LibError, match="host"):
        client.download(tmp_path, order_id="4242")
    assert not any(r.url.startswith("https://evil") for r in transport.requests)
    inside = Path(__file__).parent / "downloads"
    with pytest.raises(LibError, match="git repository"):
        client.download(inside, order_id="4242")
    assert not inside.exists()
