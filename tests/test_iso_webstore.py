"""The ISO webstore client (`primarysource.iso.webstore`): secrets, sign-in, GraphQL, the guarded basket and
free order, catalog search, stubs and the local index, and the bounded sync. A fake transport, invented values."""

from __future__ import annotations

import json
import pickle
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_iso_webstore_fakes import (
    BASE,
    SECRET_NAME,
    SECRET_PASSPHRASE,
    SESSION_COOKIE,
    item,
    json_reply,
    login_page,
    make_session,
    order,
    reply,
    store_page,
    summary,
)

from primarysource.errors import LibError
from primarysource.fetch import USER_AGENT
from primarysource.iso.webstore import (
    AddConfirmation,
    Basket,
    CatalogEntry,
    CatalogSearch,
    CatalogStore,
    Credentials,
    FreeOrderConfirmation,
    GraphQLClient,
    HttpRequest,
    HttpResponse,
    Price,
    ProductCode,
    Secret,
    SessionCache,
    login,
    sign_in,
    sync_catalog,
)
from primarysource.iso.webstore.models import entries_from_summary, parse_summary
from primarysource.iso.webstore.search import HARD_MAX_PAGES, parse_config, parse_hit
from primarysource.settings import NetworkDisabled

PACKAGE = Path(__file__).resolve().parent.parent / "primarysource" / "iso" / "webstore"


# --- secrets -----------------------------------------------------------------------------------------------------


def test_secret_never_prints() -> None:
    secret = Secret(SECRET_PASSPHRASE)
    for text in (
        repr(secret),
        str(secret),
        f"{secret}",
        f"{secret!r}",
        "%s" % secret,  # noqa: UP031
        repr([secret]),
        repr({"k": secret}),
    ):  # noqa: UP031
        assert SECRET_PASSPHRASE not in text
    assert secret.reveal() == SECRET_PASSPHRASE
    with pytest.raises(TypeError):
        pickle.dumps(secret)
    credentials = Credentials(Secret(SECRET_NAME), secret)
    assert SECRET_PASSPHRASE not in repr(credentials) and SECRET_NAME not in repr(credentials)


def test_credentials_from_env_names_the_missing_variable() -> None:
    with pytest.raises(LibError) as error:
        Credentials.from_env({"PRIMARYSOURCE_ISO_USERNAME": "x"})
    assert "PRIMARYSOURCE_ISO_PASSWORD" in error.value.message
    good = Credentials.from_env(
        {"PRIMARYSOURCE_ISO_USERNAME": SECRET_NAME, "PRIMARYSOURCE_ISO_PASSWORD": SECRET_PASSPHRASE}
    )
    assert good.password.reveal() == SECRET_PASSPHRASE


# --- the session -------------------------------------------------------------------------------------------------


def test_session_checks_hosts_spaces_requests_and_sends_a_generic_agent() -> None:
    session, transport, sleeps = make_session(lambda r: reply(200, "ok"))
    session.request("GET", f"{BASE}/a")
    session.request("GET", f"{BASE}/b")
    assert sleeps and sleeps[0] == pytest.approx(1.0)
    assert transport.requests[0].headers["User-Agent"] == USER_AGENT
    assert not re.search(r"@|\\|/Users/", USER_AGENT)
    for bad in (
        "http://www.iso.org/x",
        "https://evil.example/x",
        "https://user:pw@www.iso.org/x",
        "https://www.iso.org:8443/x",
    ):
        with pytest.raises(LibError):
            session.request("GET", bad)
    assert len(transport.requests) == 2


def test_session_refuses_a_redirect_to_another_host_and_honours_offline() -> None:
    session, transport, _ = make_session(lambda r: reply(302, "", Location="https://evil.example/x"))
    with pytest.raises(LibError):
        session.request("GET", f"{BASE}/a")
    assert len(transport.requests) == 1
    offline, transport, _ = make_session(lambda r: reply(200), environ={"PRIMARYSOURCE_ISO_NETWORK": "offline"})
    with pytest.raises(NetworkDisabled):
        offline.request("GET", f"{BASE}/a")
    assert transport.requests == []
    readonly, transport, _ = make_session(lambda r: reply(200), environ={"PRIMARYSOURCE_READONLY": "1"})
    with pytest.raises(NetworkDisabled):
        readonly.request("GET", f"{BASE}/a")


# --- sign-in -----------------------------------------------------------------------------------------------------


def _idp(on_post: HttpResponse | None = None, form: str | None = None) -> Any:
    def handler(request: HttpRequest) -> HttpResponse:
        if request.url.startswith(f"{BASE}/webstore/oauth2/authorization/iso"):
            return reply(
                302, "", Location="https://idp.iso.org/realms/test/protocol/openid-connect/auth?response_type=code"
            )
        if request.url.startswith("https://idp.iso.org/realms/test/protocol/openid-connect/auth"):
            return reply(200, form or login_page())
        if request.url.startswith("https://idp.iso.org/realms/test/login-actions/authenticate"):
            assert request.method == "POST"
            return on_post or reply(302, "", Location=f"{BASE}/webstore/login/oauth2/code/iso?code=x")
        if request.url.startswith(f"{BASE}/webstore/login/oauth2/code/iso"):
            return reply(302, "", Location=f"{BASE}/webstore/")
        if request.url == f"{BASE}/webstore/":
            return reply(200, "home")
        if request.url.endswith("/webstore/graphql"):
            return json_reply(
                {
                    "data": {
                        "currentUser": {
                            "username": "u",
                            "displayName": "d",
                            "preferredLanguage": "en",
                            "roles": ["USER"],
                            "hasCredentials": True,
                        }
                    }
                }
            )
        raise AssertionError(request.url)

    return handler


def test_login_posts_the_form_fields_once_and_signs_in() -> None:
    session, transport, _ = make_session(_idp())
    graphql = GraphQLClient(session)
    state = sign_in(session, graphql, Credentials(Secret(SECRET_NAME), Secret(SECRET_PASSPHRASE)))
    assert state.signed_in and state.roles == ("USER",)
    post = transport.calls("POST", "login-actions/authenticate")[0]
    assert post.body is not None
    fields = dict(x.split("=", 1) for x in post.body.decode().split("&"))
    assert set(fields) == {"username", "password", "credentialId", "login"}
    assert post.headers["Content-Type"] == "application/x-www-form-urlencoded"
    # the password travels in that one body and nowhere else
    assert [r for r in transport.requests if SECRET_PASSPHRASE.encode() in (r.body or b"")] == [post]
    assert not any(SECRET_PASSPHRASE in r.url for r in transport.requests)
    assert not hasattr(state, "username")


def test_login_failures_say_what_to_do_and_leak_nothing() -> None:
    credentials = Credentials(Secret(SECRET_NAME), Secret(SECRET_PASSPHRASE))
    for page, expect in (
        (reply(200, login_page()), "refused the sign-in"),
        (
            reply(200, "<html><form id='kc-update' action='/x'><input name='accept'></form></html>"),
            "asks for something",
        ),
    ):
        session, _, _ = make_session(_idp(on_post=page))
        with pytest.raises(LibError) as error:
            login(session, credentials)
        text = error.value.as_text()
        assert expect in text and SECRET_PASSPHRASE not in text and SECRET_NAME not in text
    session, _, _ = make_session(_idp(form="<html>no form here</html>"))
    with pytest.raises(LibError) as missing:
        login(session, credentials)
    assert "no login form" in missing.value.message


def test_session_cache_is_used_before_a_login_and_refuses_a_repository(tmp_path: Path) -> None:
    cache = SessionCache(tmp_path / "cache.json")
    cache.save({"SESSION": SESSION_COOKIE})
    assert cache.load() == {"SESSION": SESSION_COOKIE}
    session, transport, _ = make_session(_idp())
    state = sign_in(session, GraphQLClient(session), None, cache)
    assert state.signed_in and transport.cookies() == {"SESSION": SESSION_COOKIE}
    assert not transport.calls("GET", "oauth2/authorization")
    repo = tmp_path / "work"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(LibError):
        SessionCache(repo / "cache.json").save({"SESSION": SESSION_COOKIE})
    assert SessionCache.from_env({}) is None
    assert SessionCache.from_env({"PRIMARYSOURCE_ISO_TOKEN_FILE": str(tmp_path / "x")}) == SessionCache(
        tmp_path / "x"
    )


# --- GraphQL, the basket, the free order -------------------------------------------------------------------------


class Store:
    """A scripted webstore: a current order, and a record of every mutation."""

    def __init__(self, current: dict[str, Any], basket_total: float = 0.0) -> None:
        self.current = current
        self.basket_total = basket_total
        self.free_orders: list[dict[str, Any]] = []
        self.adds: list[str] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.url.endswith("/webstore/graphql"):
            body = json.loads(request.body or b"{}")
            op = body["operationName"]
            if op == "currentOrder":
                return json_reply({"data": {"currentOrder": self.current}})
            if op == "processFreeOrder":
                self.free_orders.append(body["variables"])
                return json_reply({"data": {"processFreeOrder": summary()}})
            if op == "orderSummary":
                return json_reply({"data": {"orderSummary": summary()}})
            return json_reply({"errors": [{"message": f"unknown {op}"}]})
        if "/webstore/MiniShoppingBasket" in request.url:
            self.adds.append(request.url)
            return json_reply({"itemCount": 1, "totalAmount": self.basket_total, "currency": "CHF"})
        if "/webstore/shoppingbasket/summary" in request.url:
            return json_reply({"itemCount": 1, "totalAmount": 0.0, "currency": "CHF"})
        raise AssertionError(request.url)


def _basket(store: Store) -> tuple[Basket, Store]:
    session, _, _ = make_session(store)
    return Basket(session, GraphQLClient(session), now=lambda: 1.0), store


FREE = order([item("ISO/IEC 99999")])
PURCHASE_ID = "a~b~c~d"


def test_graphql_errors_become_lib_errors() -> None:
    session, _, _ = make_session(lambda r: json_reply({"errors": [{"message": "boom"}]}))
    with pytest.raises(LibError) as error:
        GraphQLClient(session).execute("currentOrder", "query currentOrder { x }")
    assert "boom" in error.value.message
    session, _, _ = make_session(lambda r: reply(403))
    with pytest.raises(LibError):
        GraphQLClient(session).execute("currentOrder", "query currentOrder { x }")


def test_current_order_and_basket_summary_parse_money_as_decimal() -> None:
    basket, _ = _basket(Store(order([item("ISO 1", unit=227.0, fmt="PDF + ePub")], total=227.0)))
    placed = basket.current_order()
    assert placed.total == Decimal("227.0") and placed.items[0].unit_price == Decimal("227.0")
    assert placed.items[0].format == "PDF + ePub" and "ccc" not in repr(placed)  # the checksum is not in repr
    counter = basket.summary()
    assert counter.item_count == 1 and counter.currency == "CHF"


def test_add_is_a_dry_run_without_a_confirmation() -> None:
    basket, store = _basket(Store(FREE))
    result = basket.add(PURCHASE_ID)
    assert (
        not result.executed
        and store.adds == []
        and "<7 chars>" in result.request
        and PURCHASE_ID not in result.request
    )
    with pytest.raises(LibError):
        basket.add("not-a-purchase-id")


def test_add_executes_only_with_a_matching_confirmation_and_checks_the_total() -> None:
    basket, store = _basket(Store(FREE, basket_total=0.0))
    with pytest.raises(LibError):
        basket.add(PURCHASE_ID, AddConfirmation("other~b~c~d", "ISO/IEC 99999", Decimal(0)))
    assert store.adds == []
    done = basket.add(PURCHASE_ID, AddConfirmation(PURCHASE_ID, "ISO/IEC 99999", Decimal(0)))
    assert done.executed and len(store.adds) == 1 and done.basket is not None and done.basket.total == 0
    basket, store = _basket(Store(FREE, basket_total=227.0))
    with pytest.raises(LibError) as mismatch:
        basket.add(PURCHASE_ID, AddConfirmation(PURCHASE_ID, "ISO/IEC 99999", Decimal(0)))
    assert "remove it in a browser" in mismatch.value.hint


def test_free_order_is_a_dry_run_until_confirmed() -> None:
    basket, store = _basket(Store(FREE))
    plan = basket.plan_free_order()
    assert not plan.executed and plan.problems == () and store.free_orders == []
    assert plan.would_send["orderChecksum"] == "<redacted>"
    assert not basket.free_order().executed and store.free_orders == []


def test_free_order_executes_with_a_matching_confirmation() -> None:
    basket, store = _basket(Store(FREE))
    confirm = FreeOrderConfirmation(frozenset({"ISO/IEC 99999"}), Decimal(0), accept_withdrawal_consent=True)
    result = basket.free_order(confirm)
    assert result.executed and result.summary is not None and result.summary.total == 0
    assert store.free_orders == [
        {
            "isShareDataAccepted": False,
            "isEmailNotificationAccepted": False,
            "isWithdrawalConsentAccepted": True,
            "orderChecksum": "c" * 64,
        }
    ]


@pytest.mark.parametrize(
    "current",
    [
        order([item("ISO 1", unit=227.0)], total=227.0),  # a priced line
        order([item("ISO/IEC 99999")], total=14.3),  # the server total is not zero though the line is
        order([item("ISO/IEC 99999")], tax=1.0),
        order([item("ISO/IEC 99999")], shipping=5.0),
        order([item("ISO/IEC 99999"), item("ISO/IEC 99999", fmt="Paper", media="Print")]),  # ships
        order([item("ISO/IEC 99999"), item("ISO/IEC 11111")]),  # a line not confirmed
        order([]),
    ],
)
def test_free_order_refuses_unless_the_server_says_zero(current: dict[str, Any]) -> None:
    basket, store = _basket(Store(current))
    confirm = FreeOrderConfirmation(frozenset({"ISO/IEC 99999"}), Decimal(0), accept_withdrawal_consent=True)
    with pytest.raises(LibError) as error:
        basket.free_order(confirm)
    assert "nothing was sent" in error.value.hint
    assert store.free_orders == []
    assert basket.plan_free_order().problems or current["items"] != [item("ISO/IEC 99999")]


@pytest.mark.parametrize(
    "confirm",
    [
        FreeOrderConfirmation(frozenset({"ISO/IEC 99999"}), Decimal("1.00"), accept_withdrawal_consent=True),
        FreeOrderConfirmation(frozenset({"ISO/IEC 99999"}), Decimal(0), accept_withdrawal_consent=False),
        FreeOrderConfirmation(frozenset({"ISO/IEC 11111"}), Decimal(0), accept_withdrawal_consent=True),
        FreeOrderConfirmation(frozenset(), Decimal(0), accept_withdrawal_consent=True),
    ],
)
def test_free_order_refuses_a_confirmation_that_does_not_match(confirm: FreeOrderConfirmation) -> None:
    basket, store = _basket(Store(FREE))
    with pytest.raises(LibError):
        basket.free_order(confirm)
    assert store.free_orders == []


def test_a_placed_order_with_a_nonzero_total_is_reported() -> None:
    class Odd(Store):
        def __call__(self, request: HttpRequest) -> HttpResponse:
            if request.url.endswith("/webstore/graphql") and b"processFreeOrder" in (request.body or b""):
                return json_reply({"data": {"processFreeOrder": summary(total=9.0)}})
            return super().__call__(request)

    basket, _ = _basket(Odd(FREE))
    with pytest.raises(LibError):
        basket.free_order(
            FreeOrderConfirmation(frozenset({"ISO/IEC 99999"}), Decimal(0), accept_withdrawal_consent=True)
        )


def test_there_is_no_payment_or_deletion_code() -> None:
    sources = "\n".join(p.read_text("utf-8") for p in PACKAGE.glob("*.py"))
    for forbidden in (
        "mutation deleteOrderItem",
        "mutation updateUserDetails",
        "mutation updatePurchaseOrderNumber",
        "mutation startUserSession",
    ):
        assert forbidden not in sources
    assert re.findall(r"mutation (\w+)\(", sources) == ["processFreeOrder"]


def test_summary_entries_carry_the_product_code_year_and_price() -> None:
    entries = entries_from_summary(parse_summary(summary()))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.designation == "ISO/IEC 99999-1:2031" and entry.product_code == "iso:std:iso-iec:99999:-1"
    assert entry.price == Price(Decimal("0.0"), "CHF") and entry.is_free is True
    assert ProductCode.parse("iso:std:iso:14229:-1") == ProductCode("iso", "14229", "-1")
    assert ProductCode.parse("nonsense") is None


# --- catalog search ----------------------------------------------------------------------------------------------

HITS: list[dict[str, Any]] = [
    {
        "reference": "ISO 99999-1:2031",
        "title": "Invented widgets, part 1",
        "text": "Invented abstract about widgets.",
        "category": "standard",
        "statusKey": "ENT_ACTIVE",
        "seoURL": "/standard/12345.html",
        "path": "/sites/isoorg/x",
        "ics": ["35.100.10"],
        "committee": "ISO/TC 999",
    },
    {
        "title": "Invented committee",
        "category": "committee",
        "statusKey": "ENT_PROGRESS",
        "seoURL": "/committee/999.html",
    },
]


def _algolia(key_valid_until: int = 4102444800, pages: int = 1) -> Any:
    seen: list[HttpRequest] = []

    def handler(request: HttpRequest) -> HttpResponse:
        seen.append(request)
        if request.url == f"{BASE}/store.html":
            return reply(200, store_page(key_valid_until))
        if request.url == "https://testapp01-dsn.algolia.net/1/indexes/*/queries":
            params = json.loads(request.body or b"{}")["requests"][0]["params"]
            page = int(re.search(r"page=(\d+)", params)[1])  # type: ignore[index]
            return json_reply(
                {"results": [{"hits": HITS, "nbHits": 4, "page": page, "nbPages": pages, "hitsPerPage": 2}]}
            )
        raise AssertionError(request.url)

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def test_config_is_read_from_the_page_and_key_expiry_is_decoded() -> None:
    config = parse_config(store_page())
    assert (
        config.app_id == "TESTAPP01"
        and config.index == "TEST_index_en"
        and config.host == "testapp01-dsn.algolia.net"
    )
    assert config.expires() is not None and config.expires().year == 2100  # type: ignore[union-attr]
    assert config.api_key.reveal() not in repr(config)
    with pytest.raises(LibError):
        parse_config("<html>nothing</html>")


def test_hits_become_catalog_entries_and_category_is_filtered() -> None:
    entry = parse_hit(HITS[0])
    assert entry.designation == "ISO 99999-1:2031" and entry.status == "active" and entry.ics == ("35.100.10",)
    assert entry.url == f"{BASE}/standard/12345.html" and entry.price is None and entry.is_free is None
    handler = _algolia()
    session, transport, _ = make_session(handler)
    search = CatalogSearch(session)
    page = search.search("widgets", category="standard")
    assert [hit.designation for hit in page.hits] == ["ISO 99999-1:2031"]
    sent = transport.calls("POST", "algolia")[0]
    assert sent.headers["X-Algolia-Application-Id"] == "TESTAPP01" and "X-Algolia-API-Key" in sent.headers
    assert json.loads(sent.body or b"")["requests"][0]["indexName"] == "TEST_index_en"


def test_search_bounds_and_expired_keys() -> None:
    session, transport, _ = make_session(_algolia())
    search = CatalogSearch(session)
    for kwargs in (
        {"query": "  "},
        {"query": "x", "category": "nope"},
        {"query": "x", "page": HARD_MAX_PAGES},
        {"query": "x", "hits_per_page": 500},
    ):
        with pytest.raises(LibError):
            search.search(**kwargs)
    assert transport.requests == []
    expired = _algolia(key_valid_until=1000000000)
    session, transport, _ = make_session(expired)
    CatalogSearch(session).search("x")
    assert len(transport.calls("GET", "store.html")) == 1
    # a second search with an already-expired key reads the page again rather than using it
    search = CatalogSearch(
        session, now=lambda: __import__("datetime").datetime(2001, 1, 1, tzinfo=__import__("datetime").UTC)
    )
    search.search("x")
    search.search("x")
    assert len(transport.calls("GET", "store.html")) == 2


# --- stubs and the index ------------------------------------------------------------------------------------------


def _entries() -> list[CatalogEntry]:
    return [
        CatalogEntry(
            "standard",
            "ISO 99999-1:2031",
            "Invented widgets",
            status="active",
            price=Price(Decimal("227.00"), "CHF"),
            ics=("35.100.10",),
            committee="ISO/TC 999",
            formats=("PDF", "Paper"),
            product_code="iso:std:iso:99999:-1",
        ),
        CatalogEntry(
            "standard", "ISO/IEC 88888:2030", "Invented gadgets", status="inactive", price=Price(Decimal(0), "CHF")
        ),
        CatalogEntry("committee", "", "Invented committee on widgets", committee="ISO/TC 999"),
        CatalogEntry("ics", "35.100", "Invented open systems interconnection"),
    ]


def test_stubs_and_index_make_metadata_searchable_without_any_text(tmp_path: Path) -> None:
    store = CatalogStore(tmp_path / "webstore")
    assert store.write_all(_entries()) == 4
    assert store.build_index() == 4
    assert "ISO 99999-1:2031" in [f.entry.designation for f in store.search("widgets")]
    assert [f.entry.designation for f in store.search("price free")] == ["ISO/IEC 88888:2030"] or store.search(
        "free", free=True
    )
    assert [f.entry.designation for f in store.search("invented", free=True)] == ["ISO/IEC 88888:2030"]
    assert [f.entry.designation for f in store.search("invented", free=False)] == ["ISO 99999-1:2031"]
    assert [f.entry.designation for f in store.search("invented", status="inactive")] == ["ISO/IEC 88888:2030"]
    assert [f.entry.kind for f in store.search("invented", category="ics")] == ["ics"]
    assert [f.entry.designation for f in store.search("35.100.10")] == [
        "ISO 99999-1:2031"
    ]  # an ICS code is a keyword
    assert store.search("227.00")  # the price is a keyword too
    assert [e.title for e in store.browse("committee")] == ["Invented committee on widgets"]
    again = [CatalogEntry.from_json(json.loads(p.read_text("utf-8"))) for p in sorted(store.stubs.glob("*.json"))]
    assert {e.key for e in again} == {e.key for e in _entries()}


def test_a_missing_index_is_an_error_naming_the_command(tmp_path: Path) -> None:
    with pytest.raises(LibError) as error:
        CatalogStore(tmp_path / "w").search("x")
    assert "index" in error.value.hint


def test_stubs_are_refused_inside_a_repository(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(LibError):
        CatalogStore(tmp_path / "webstore").write(_entries()[0])


# --- the bounded sync ---------------------------------------------------------------------------------------------


def test_sync_is_opt_in_bounded_and_polite(tmp_path: Path) -> None:
    session, transport, sleeps = make_session(_algolia(pages=5))
    store = CatalogStore(tmp_path / "webstore")
    search = CatalogSearch(session)
    with pytest.raises(LibError) as refused:
        sync_catalog(search, store, ["widgets"])
    assert "opt-in" in refused.value.message and transport.requests == []
    with pytest.raises(LibError):
        sync_catalog(search, store, ["widgets"], opt_in=True, max_pages=HARD_MAX_PAGES + 1)
    with pytest.raises(LibError):
        sync_catalog(search, store, [f"q{i}" for i in range(26)], opt_in=True)
    report = sync_catalog(search, store, ["widgets"], opt_in=True, max_pages=3)
    assert report.requests == 3 and report.written == 6
    assert len(transport.calls("POST", "algolia")) == 3
    assert all(abs(s - 1.0) < 1e-9 for s in sleeps) and len(sleeps) == 3  # one request a second
    assert all(r.headers["User-Agent"] == USER_AGENT for r in transport.requests)


def test_sync_stops_before_the_first_request_when_offline(tmp_path: Path) -> None:
    session, transport, _ = make_session(_algolia(), environ={"PRIMARYSOURCE_NETWORK": "offline"})
    with pytest.raises(NetworkDisabled):
        sync_catalog(CatalogSearch(session), CatalogStore(tmp_path / "w"), ["widgets"], opt_in=True)
    assert transport.requests == []


# --- hygiene ------------------------------------------------------------------------------------------------------


def test_nothing_in_the_package_or_docs_looks_like_a_credential() -> None:
    docs = PACKAGE.parent.parent.parent / "docs" / "iso-webstore.md"
    texts = [p.read_text("utf-8") for p in PACKAGE.glob("*.py")] + (
        [docs.read_text("utf-8")] if docs.exists() else []
    )
    for text in texts:
        assert not re.search(r"[A-Za-z0-9+/=]{60,}", text.replace("`", " ")), "a long opaque string"
        assert not re.search(r"[\w.+-]+@(?!example\.)[\w-]+\.(com|org|net)", text.replace("copyright@iso.org", "")), (
            "an e-mail address"
        )
        assert "Bearer " not in text


# --- the filter API and the extra catalog fields ------------------------------------------------------------------


def test_filters_select_by_price_free_ics_committee_status_and_language(tmp_path: Path) -> None:
    from primarysource.iso.webstore import CatalogFilter

    rich = CatalogEntry(
        "standard",
        "ISO 11111:2020",
        "Invented",
        status="active",
        price=Price(Decimal("120.00"), "CHF"),
        ics=("35.100.10", "01.040.35"),
        committee="ISO/IEC JTC 1/SC 6",
        language="en",
        pages=42,
        published="2020-05-01",
        supersedes=("ISO 11111:2010",),
        superseded_by=("ISO 11111:2030",),
        toc=("1 Scope", "2 Terms"),
    )
    cheap = CatalogEntry(
        "standard", "ISO 22222:2021", "Invented", status="inactive", price=Price(Decimal("30.00"), "CHF")
    )
    free = CatalogEntry("standard", "ISO 33333:2022", "Invented", status="active", price=Price(Decimal(0), "CHF"))
    unknown = CatalogEntry("standard", "ISO 44444:2023", "Invented", status="active")
    store = CatalogStore(tmp_path / "w")
    store.write_all([rich, cheap, free, unknown])

    def names(where: CatalogFilter, query: str | None = None) -> list[str]:
        return [e.designation for e in store.select(where, query)]

    assert names(CatalogFilter(free=True)) == ["ISO 33333:2022"]
    assert names(CatalogFilter(free=False)) == ["ISO 11111:2020", "ISO 22222:2021"]
    assert names(CatalogFilter(min_price=Decimal(50))) == ["ISO 11111:2020"]
    assert names(CatalogFilter(max_price=Decimal(50))) == [
        "ISO 22222:2021",
        "ISO 33333:2022",
    ]  # unknown price is excluded
    assert names(CatalogFilter(ics_prefix="35.100")) == ["ISO 11111:2020"]
    assert names(CatalogFilter(ics_prefix="01.")) == ["ISO 11111:2020"]
    assert names(CatalogFilter(committee_prefix="ISO/IEC JTC 1")) == ["ISO 11111:2020"]
    assert names(CatalogFilter(status="inactive")) == ["ISO 22222:2021"]
    assert names(CatalogFilter(language="en")) == ["ISO 11111:2020"]
    store.build_index()
    assert sorted(names(CatalogFilter(max_price=Decimal(50)), "invented")) == ["ISO 22222:2021", "ISO 33333:2022"]
    assert names(CatalogFilter(free=False), "superseded 2030") == ["ISO 11111:2020"]
    back = next(store.entries())
    assert CatalogEntry.from_json(back.to_json()) == back
    assert next(e for e in store.entries() if e.pages == 42).superseded_by == ("ISO 11111:2030",)
    hit = parse_hit(
        {
            "reference": "ISO 1",
            "pages": "42",
            "language": "en",
            "publicationDate": "2020-05-01",
            "supersededBy": "ISO 2",
        }
    )
    assert hit.pages == 42 and hit.published == "2020-05-01" and hit.superseded_by == ("ISO 2",)
