"""iec webstore: secrets, transport, models, search, the local catalogue. Offline, over invented fixtures.

Nothing here is IEC text: designations, titles, committees, prices and ids are made up, and the response shapes
are the ones the capture showed. No request leaves the process: every client is given `FakeTransport`.
"""

from __future__ import annotations

import json
import pickle
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from primarysource.errors import LibError
from primarysource.iec.webstore import (
    Credentials,
    HttpRequest,
    HttpResponse,
    PoliteTransport,
    SearchClient,
    SearchQuery,
    Secret,
    find,
    rebuild_index,
    sync_catalog,
    write_stubs,
)
from primarysource.iec.webstore.catalog import HARD_MAX_PAGES, catalog_home, filter_catalog, load_stub
from primarysource.iec.webstore.models import parse_publication, parse_search
from primarysource.iec.webstore.transport import (
    USER_AGENT,
    UrllibTransport,
    download_host_allowed,
    ensure_outside_repository,
)
from primarysource.settings import NetworkDisabled

# --- the fake wire -----------------------------------------------------------------------------------------------


class FakeStream:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self._pos = 0
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def header(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def read(self, size: int) -> bytes:
        chunk = self._body[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


Handler = Callable[[HttpRequest], HttpResponse]


class FakeTransport:
    """Routes `(method, url-prefix)` to a response or a handler; records every request; holds a cookie dict."""

    def __init__(self) -> None:
        self.routes: list[tuple[str, str, Handler]] = []
        self.requests: list[HttpRequest] = []
        self.cookies: dict[str, str] = {}
        self.streams: dict[str, FakeStream] = {}

    def route(self, method: str, prefix: str, response: HttpResponse | Handler) -> None:
        handler = response if callable(response) else (lambda _r, _x=response: _x)
        self.routes.insert(0, (method, prefix, handler))

    def json_route(self, method: str, prefix: str, data: Any, status: int = 200) -> None:
        self.route(
            method, prefix, HttpResponse(status, {"content-type": "application/json"}, json.dumps(data).encode())
        )

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        for method, prefix, handler in self.routes:
            if request.method == method and request.url.startswith(prefix):
                return handler(request)
        return HttpResponse(404, {}, b"")

    @contextmanager
    def open_stream(self, request: HttpRequest) -> Iterator[FakeStream]:
        self.requests.append(request)
        yield self.streams.get(request.url, FakeStream(404, b""))

    def cookie(self, name: str) -> str | None:
        return self.cookies.get(name)

    def set_cookie(self, name: str, value: str) -> None:
        self.cookies[name] = value

    def posts(self) -> list[HttpRequest]:
        return [r for r in self.requests if r.method == "POST"]


# --- invented catalogue data in the observed shape ----------------------------------------------------------------


def source(ident: int, reference: str, price: float, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": ident,
        "reference": reference,
        "title": f"Invented title for {reference}",
        "edition": "2.0",
        "status": "PUBLISHED",
        "publication_type": "STANDARD",
        "publication_date": "2099-01-02",
        "reference_object": {"head": "XYZ", "num": str(ident)},
        "price": {"amount": price, "currency": "CHF"},
        "committee": {
            "level_1": "TC 999",
            "level_1_details": "Invented committee",
            "level_2": "SC 999A",
            "level_2_details": "Invented subcommittee",
        },
        "ics": [
            {
                "level_1": "99",
                "level_2": "99.100",
                "level_3": "99.100.10",
                "level_1_details": "INVENTED FIELD",
                "level_2_details": "Invented group",
                "level_3_details": "Invented subject",
            }
        ],
        "available_formats": ["PDF", "XML"],
        "available_files": [
            {"format": "PDF", "language": "en", "type": "STANDARD", "hasFullPdf": True},
            {"format": "PDF", "language": "fr", "type": "STANDARD", "hasFullPdf": True},
        ],
        "pdf_pages": 12,
        "isbn": "0000000000000",
        "urn": f"iec:pub:{ident}",
        "lifecycle": [{"reference": f"{reference}-old", "id": "1", "edition": "1.0", "status": "REVISED"}],
        "abstract": "Invented abstract about gadgets.",
    }
    base.update(extra)
    return base


def bucket_tree(keys: list[tuple[str, int]]) -> dict[str, Any]:
    return {
        "meta": [],
        "doc_count": 3,
        "root": {"nested": {"buckets": [{"key": k, "doc_count": c} for k, c in keys]}},
    }


def search_payload(sources: list[dict[str, Any]], total: int | None = None, unfiltered: int = 50) -> dict[str, Any]:
    hits = [{"_id": str(s["id"]), "_source": s} for s in sources]
    block = {
        "hits": {"total": {"value": len(sources) if total is None else total}, "hits": hits},
        "aggregations": {
            "buckets#committee": bucket_tree([("TC 999", 3), ("TC 998", 1)]),
            "buckets#type": bucket_tree([("IS", 3)]),
        },
    }
    other = {"hits": {"total": {"value": unfiltered}, "hits": []}, "aggregations": {}}
    return {"primary": other, "secondary": block}


# --- secrets -----------------------------------------------------------------------------------------------------


def test_secret_never_shows_its_value() -> None:
    secret = Secret("hunter2-invented")
    for shown in (repr(secret), str(secret), f"{secret}", f"{secret!r}", "%s" % secret):  # noqa: UP031
        assert "hunter2" not in shown
    assert secret.reveal() == "hunter2-invented"
    with pytest.raises(TypeError):
        pickle.dumps(secret)


def test_credentials_come_from_the_environment_and_are_redacted() -> None:
    creds = Credentials.from_env(
        {"PRIMARYSOURCE_IEC_USERNAME": "someone", "PRIMARYSOURCE_IEC_PASSWORD": "pw-invented"}
    )
    assert "someone" not in repr(creds) and "pw-invented" not in repr(creds)
    assert creds.username.reveal() == "someone"
    with pytest.raises(LibError) as error:
        Credentials.from_env({})
    assert "PRIMARYSOURCE_IEC_PASSWORD" in error.value.hint


# --- transport -----------------------------------------------------------------------------------------------------


def test_polite_transport_waits_between_requests_and_sets_a_generic_user_agent() -> None:
    inner = FakeTransport()
    inner.route("GET", "https://webstore.iec.ch/", HttpResponse(200, {}, b"ok"))
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    polite = PoliteTransport(inner, clock=lambda: now[0], sleep=sleep, environ={})
    polite.send(HttpRequest("GET", "https://webstore.iec.ch/a", {"User-Agent": "someone-else"}))
    polite.send(HttpRequest("GET", "https://webstore.iec.ch/b"))
    assert slept == [1.0]
    assert {r.headers["User-Agent"] for r in inner.requests} == {USER_AGENT}
    assert "@" not in USER_AGENT


def test_polite_transport_refuses_when_the_collection_is_offline() -> None:
    inner = FakeTransport()
    polite = PoliteTransport(inner, environ={"PRIMARYSOURCE_IEC_NETWORK": "offline"})
    with pytest.raises(NetworkDisabled):
        polite.send(HttpRequest("GET", "https://webstore.iec.ch/a"))
    assert inner.requests == []


def test_urllib_transport_refuses_before_any_request() -> None:
    transport = UrllibTransport()
    for url in (
        "http://webstore.iec.ch/en/",
        "https://example.org/",
        "https://user:pw@webstore.iec.ch/",
        "https://webstore.iec.ch:8443/",
    ):
        with pytest.raises(LibError):
            transport.send(HttpRequest("GET", url))
    transport.set_cookie("form_key", "abc")
    assert transport.cookie("form_key") == "abc"


def test_download_host_and_repository_guards(tmp_path: Path) -> None:
    assert download_host_allowed("storage-watermark-prd-example.s3.eu-west-1.amazonaws.com")
    assert not download_host_allowed("evil.example.org")
    assert not download_host_allowed("storage-watermark-x.evil.org")
    assert not download_host_allowed(None)
    assert ensure_outside_repository(tmp_path / "x") == (tmp_path / "x").resolve()
    with pytest.raises(LibError, match="git repository"):
        ensure_outside_repository(Path(__file__).parent / "out")
    with pytest.raises(LibError):
        UrllibTransport(session_file=Path(__file__).parent / "jar.txt")


# --- models and search ---------------------------------------------------------------------------------------------


def test_parse_publication_reads_metadata_and_flags_free() -> None:
    free = parse_publication(source(1001, "XYZ 1:2099", 0))
    paid = parse_publication(source(1002, "XYZ 2:2099", 405))
    assert free.is_free and not paid.is_free
    assert str(paid.price) == "CHF 405"
    assert free.committee is not None and free.committee.level_1 == "TC 999"
    assert free.ics[0].code == "99.100.10" and free.ics[0].title == "Invented subject"
    assert free.languages == ("en", "fr") and free.formats == ("PDF", "XML")
    assert free.lifecycle[0].status == "REVISED" and free.page_url.endswith("/publication/1001")
    assert "abstract" not in repr(free)


def test_parse_publication_without_id_is_an_error_with_a_hint() -> None:
    with pytest.raises(LibError) as error:
        parse_publication({"title": "x"})
    assert error.value.hint


def test_parse_search_takes_the_filtered_list_and_flattens_facets() -> None:
    page = parse_search(search_payload([source(1, "A 1", 0), source(2, "A 2", 5)], total=7, unfiltered=50), start=0)
    assert [h.id for h in page.hits] == [1, 2]
    assert (page.total, page.unfiltered_total, page.next_start) == (7, 50, 2)
    assert page.facets["committee"] == (("TC 999", 3), ("TC 998", 1))
    last = parse_search(search_payload([source(3, "A 3", 1)], total=3), start=2)
    assert last.next_start is None
    with pytest.raises(LibError):
        parse_search({"unexpected": 1})


def test_search_payload_has_the_observed_keys_and_no_credentials() -> None:
    query = SearchQuery(text="invented").with_terms(committee=["TC 999"], type=["IS"])
    payload = query.payload(start=25, size=25)
    assert set(payload) == {
        "mode", "query", "from", "size", "validOnly", "sortBy", "language", "dateRanges", "terms", "publicationIds",
        "showTrf", "collapsed",
    }  # fmt: skip
    assert payload["terms"] == {"committee": {"1": ["TC 999"]}, "type": {"1": ["IS"]}}
    assert payload["sortBy"] == [{"reference": "asc"}] and payload["mode"] == "FULL"

    transport = FakeTransport()
    transport.json_route(
        "POST", "https://webstore-search-api.iec.ch/api/search", search_payload([source(1, "A 1", 0)])
    )
    SearchClient(transport).search(query, start=25, size=25)
    sent = transport.requests[0]
    assert json.loads(sent.body or b"")["from"] == 25
    assert not {"cookie", "authorization"} & {k.lower() for k in sent.headers}


def test_search_bounds_and_paging() -> None:
    transport = FakeTransport()
    pages = [search_payload([source(i, f"A {i}", 0) for i in range(n, n + 2)], total=6) for n in (0, 2, 4)]

    def answer(request: HttpRequest) -> HttpResponse:
        start = json.loads(request.body or b"")["from"]
        return HttpResponse(200, {}, json.dumps(pages[start // 2]).encode())

    transport.route("POST", "https://webstore-search-api.iec.ch/", answer)
    client = SearchClient(transport)
    got = list(client.pages(SearchQuery(), max_pages=10, size=2))
    assert [len(p.hits) for p in got] == [2, 2, 2] and len(transport.posts()) == 3
    assert len(list(client.pages(SearchQuery(), max_pages=1, size=2))) == 1
    with pytest.raises(LibError):
        list(client.pages(SearchQuery(), max_pages=0))
    with pytest.raises(LibError):
        client.search(SearchQuery(), size=101)
    transport.json_route("POST", "https://webstore-search-api.iec.ch/", {}, status=503)
    with pytest.raises(LibError, match="503"):
        client.search(SearchQuery())


# --- the local catalogue -------------------------------------------------------------------------------------------


def publications() -> list[Any]:
    return [
        parse_publication(source(1001, "XYZ 1:2099", 0)),
        parse_publication(
            source(1002, "XYZ 2:2099", 405, committee={"level_1": "TC 500", "level_1_details": "Other"})
        ),
    ]


def test_stubs_hold_metadata_and_the_abstract_unless_left_out(tmp_path: Path) -> None:
    home = catalog_home(tmp_path)
    assert write_stubs(home, publications()) == 2
    stub = load_stub(home, 1001)
    assert stub is not None and stub["is_free"] is True and stub["abstract"].startswith("Invented")
    assert stub["price"] == {"amount": 0, "currency": "CHF"}
    write_stubs(home, publications()[:1], include_abstract=False)
    again = load_stub(home, 1001)
    assert again is not None and "abstract" not in again


def test_index_finds_by_designation_price_committee_and_ics(tmp_path: Path) -> None:
    home = catalog_home(tmp_path)
    write_stubs(home, publications())
    assert rebuild_index(home) > 0
    hits, _, _ = find(home, "XYZ 2:2099")
    assert hits and hits[0].id == 1002 and hits[0].stub is not None
    free, _, _ = find(home, "free")
    assert {h.id for h in free} == {1001}
    committee, _, _ = find(home, "TC 500")
    assert {h.id for h in committee} == {1002}
    ics, _, _ = find(home, "99.100.10")
    assert {h.id for h in ics} == {1001, 1002}
    assert {h.id for h in find(home, "gadgets")[0]} == {1001, 1002}  # the catalogue abstract is indexed
    write_stubs(home, publications(), include_abstract=False)
    rebuild_index(home)
    assert find(home, "gadgets")[0] == ()
    assert find(home, "zzzznomatch")[0] == ()


def test_find_without_an_index_names_its_remedy(tmp_path: Path) -> None:
    with pytest.raises(LibError) as error:
        find(catalog_home(tmp_path), "x")
    assert "primarysource.iec.webstore" in error.value.hint
    with pytest.raises(LibError):
        rebuild_index(catalog_home(tmp_path))


def test_sync_is_opt_in_bounded_and_writes_under_the_given_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRIMARYSOURCE_IEC_NETWORK", raising=False)
    monkeypatch.delenv("PRIMARYSOURCE_NETWORK", raising=False)
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)
    monkeypatch.delenv("PRIMARYSOURCE_IEC_READONLY", raising=False)
    transport = FakeTransport()
    pages = [search_payload([source(10 + n, f"S {n}", 0)], total=3) for n in range(3)]
    transport.route(
        "POST",
        "https://webstore-search-api.iec.ch/",
        lambda r: HttpResponse(200, {}, json.dumps(pages[json.loads(r.body or b"")["from"]]).encode()),
    )
    client = SearchClient(transport)
    home = catalog_home(tmp_path)
    with pytest.raises(LibError, match="opt-in"):
        sync_catalog(client, home, SearchQuery())
    with pytest.raises(LibError):
        sync_catalog(client, home, SearchQuery(), opt_in=True, max_pages=HARD_MAX_PAGES + 1)
    assert transport.requests == [] and not home.exists()

    written, total = sync_catalog(client, home, SearchQuery(), opt_in=True, max_pages=2, page_size=1)
    assert (written, total) == (2, 3) and len(transport.posts()) == 2
    assert sorted(p.name for p in (home / "stubs").iterdir()) == ["10.json", "11.json"]
    assert (home / "catalog.sqlite").is_file()
    assert find(home, "S 1")[0]

    monkeypatch.setenv("PRIMARYSOURCE_IEC_NETWORK", "offline")
    with pytest.raises(NetworkDisabled):
        sync_catalog(client, home, SearchQuery(), opt_in=True)


def test_filter_by_cost_category_and_status(tmp_path: Path) -> None:
    home = catalog_home(tmp_path)
    extra = parse_publication(source(1003, "XYZ 3:2099", 810, status="WITHDRAWN", ics=[{"level_3": "33.100.10"}]))
    write_stubs(home, [*publications(), extra])

    def refs(**kw: Any) -> list[str]:
        return [s["reference"] for s in filter_catalog(home, **kw)]

    assert refs() == ["XYZ 1:2099", "XYZ 2:2099", "XYZ 3:2099"]
    assert refs(free_only=True) == ["XYZ 1:2099"]
    assert refs(min_price=400, max_price=500) == ["XYZ 2:2099"]
    assert refs(min_price=500) == ["XYZ 3:2099"]
    assert refs(status="withdrawn") == ["XYZ 3:2099"]
    assert refs(category_prefix="tc 500") == ["XYZ 2:2099"]
    assert refs(category_prefix="33.100") == ["XYZ 3:2099"]
    assert refs(category_prefix="99.100") == ["XYZ 1:2099", "XYZ 2:2099"]
    assert refs(category_prefix="99", max_price=0) == ["XYZ 1:2099"]
    assert refs(currency="EUR") == []
    with pytest.raises(LibError):
        filter_catalog(catalog_home(tmp_path / "none"))
