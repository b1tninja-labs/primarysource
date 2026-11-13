from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest
from zimfixture import contract_server, tool_error, tool_text

from primarysource.zim import catalog, cli, mcp, service, snapshot
from primarysource.zim.errors import LibraryNotFound, ZimloreError

anyio = pytest.importorskip("anyio")

# Invented catalogue: names and titles follow the live feed's conventions, the numbers are made up.
CATALOGUE: list[dict[str, Any]] = [
    {"name": "devdocs_en_acme", "title": "Acme Docs", "date": "2026-10-01", "length": 617472, "articles": 59},
    {"name": "devdocs_en_acme", "title": "Acme Docs", "date": "2026-08-01", "length": 600000, "articles": 50},
    {"name": "devdocs_en_acme_extras", "title": "Acme Extras Docs", "date": "2026-09-01", "length": 5_000_000},
    {"name": "devdocs_en_widgetry", "title": "Widgetry Docs", "date": "2026-07-01", "length": 1_200_000},
    {"name": "acme_en_widgets", "title": "Acme Widgets Docs", "date": "2026-10-15", "length": 2_000_000},
    {"name": "security.stackexchange.com_en_all", "title": "Security Stack Exchange", "date": "2026-06-01"},
    {"name": "wikipedia_en_all_maxi", "title": "Wikipedia", "date": "2026-05-01", "length": 90_000_000_000},
]


def _entry_xml(index: int, item: dict[str, Any]) -> str:
    return (
        f"<entry><id>urn:uuid:{index}</id><title>{escape(item['title'])}</title>"
        f"<updated>{item['date']}T00:00:00Z</updated><summary>Invented summary {index}</summary>"
        f"<language>eng</language><name>{item['name']}</name><tags>devdocs;_ftindex:no;demo</tags>"
        f"<articleCount>{item.get('articles', 7)}</articleCount><author><name>Tests</name></author>"
        f'<link type="application/x-zim" '
        f'href="https://example.invalid/zim/{item["name"]}_{item["date"][:7]}.zim.meta4" '
        f'length="{item.get("length", 1000)}" /></entry>'
    )


def feed(start: int, count: int, items: list[dict[str, Any]]) -> bytes:
    page = items[start : start + count]
    body = "".join(_entry_xml(start + i, item) for i, item in enumerate(page))
    return (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f"<totalResults>{len(items)}</totalResults><startIndex>{start}</startIndex>"
        f"<itemsPerPage>{len(page)}</itemsPerPage>{body}</feed>"
    ).encode()


@contextmanager
def serve(items: list[dict[str, Any]], requests: list[str] | None = None) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802
            if requests is not None:
                requests.append(self.path)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            body = feed(int(query.get("start", ["0"])[0]), int(query.get("count", ["50"])[0]), items)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/catalog"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def snap(home: Path) -> Path:
    """A written snapshot of CATALOGUE in a scratch ZIMLORE_HOME, fetched over a local HTTP server."""
    with serve(CATALOGUE) as base:
        snapshot.refresh(base=base)
    return snapshot.path()


def test_refresh_pages_through_the_feed_and_writes_every_field(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot, "PAGE_SIZE", 3)
    seen: list[str] = []
    with serve(CATALOGUE, seen) as base:
        result = snapshot.refresh(base=base)
    assert result["pages"] == 3 and len(seen) == 3
    assert [urllib.parse.parse_qs(urllib.parse.urlsplit(p).query)["start"] for p in seen] == [["0"], ["3"], ["6"]]
    assert all("lang=eng" in p and "count=3" in p for p in seen)
    assert (result["entries"], result["total_results"]) == (7, 7)
    document = json.loads(snapshot.path().read_text(encoding="utf-8"))
    assert document["schema"] == 1 and document["total_results"] == 7 and document["fetched_at"].endswith("Z")
    first = document["entries"][0]
    assert first == {
        "name": "devdocs_en_acme",
        "title": "Acme Docs",
        "date": "2026-10-01",
        "language": "eng",
        "summary": "Invented summary 0",
        "creator": "Tests",
        "articles": 59,
        "approx_bytes": 617472,
        "url": "https://example.invalid/zim/devdocs_en_acme_2026-10.zim",
        "tags": ["devdocs", "demo"],
    }
    assert not list(snapshot.path().parent.glob("*.tmp")), "the atomic write leaves no temporary file"
    assert result["bytes"] == snapshot.path().stat().st_size


def test_a_failed_or_empty_refresh_keeps_the_previous_snapshot(snap: Path) -> None:
    before = snap.read_bytes()
    with serve([]) as base, pytest.raises(ZimloreError, match="no ZIM entries"):
        snapshot.refresh(base=base)
    with pytest.raises(ZimloreError, match="could not fetch"):
        snapshot.refresh(base="http://127.0.0.1:9/none")
    assert snap.read_bytes() == before


def test_load_returns_entries_fetched_at_and_age(snap: Path) -> None:
    entries, fetched_at, age = snapshot.load()
    assert len(entries) == len(CATALOGUE) and entries[0].name == "devdocs_en_acme" and age == 0
    assert fetched_at == json.loads(snap.read_text(encoding="utf-8"))["fetched_at"]
    later = datetime.now(UTC) + timedelta(days=12, hours=3)
    assert snapshot.load(later)[2] == 12


def test_a_missing_snapshot_is_an_error_naming_the_refresh_command(home: Path) -> None:
    with pytest.raises(ZimloreError) as caught:
        snapshot.load()
    assert (
        caught.value.action == "primarysource zim catalog --refresh"
        and "no catalogue snapshot" in caught.value.message
    )


@pytest.mark.parametrize(
    "damage",
    [
        lambda d: "{not json",
        lambda d: json.dumps([]),
        lambda d: json.dumps({**d, "schema": 2}),
        lambda d: json.dumps({**d, "fetched_at": "yesterday"}),
        lambda d: json.dumps({**d, "entries": "many"}),
        lambda d: json.dumps({**d, "entries": [{"name": "x"}]}),
        lambda d: json.dumps({**d, "entries": [{**d["entries"][0], "articles": "59"}]}),
        lambda d: json.dumps({**d, "entries": [{**d["entries"][0], "name": "a b; rm -rf"}]}),
    ],
)
def test_a_corrupt_or_wrong_schema_snapshot_is_an_error_never_an_empty_one(snap: Path, damage: Any) -> None:
    snap.write_text(damage(json.loads(snap.read_text(encoding="utf-8"))), encoding="utf-8")
    with pytest.raises(ZimloreError) as caught:
        snapshot.load()
    assert "cannot be used" in caught.value.message and caught.value.action == "primarysource zim catalog --refresh"
    with pytest.raises(ZimloreError):
        snapshot.available("acme")


def test_available_ranks_like_the_library_does_and_keeps_the_latest_edition(snap: Path) -> None:
    rows = snapshot.available("acme", 10)["available"]
    names = [row["name"] for row in rows]
    assert names[0] == "devdocs_en_acme", "the exact slug beats everything"
    assert set(names) == {"devdocs_en_acme", "devdocs_en_acme_extras", "acme_en_widgets"}
    assert names.count("devdocs_en_acme") == 1 and rows[0]["date"] == "2026-10-01", "latest edition only"
    top = rows[0]
    assert (
        top["install"] == "primarysource zim get devdocs_en_acme"
        and top["approx_mb"] == 0.6
        and top["articles"] == 59
    )
    assert top["title"] == "Acme Docs" and top["installed"] is False and top["installed_edition"] is None
    assert top["snapshot_age_days"] == 0
    # exact > prefix: "acme" is the whole slug of one entry and only a prefix of another
    exact = snapshot.available("widgetry")["available"]
    assert [r["name"] for r in exact] == ["devdocs_en_widgetry"]
    fuzzy = snapshot.available("widgetri")["available"]
    assert fuzzy and fuzzy[0]["name"] == "devdocs_en_widgetry", "a near miss still finds it"
    assert snapshot.available("zzqxj")["available"] == [], "no match is an empty list with the snapshot age beside it"
    assert snapshot.available("zzqxj")["snapshot"]["age_days"] == 0


def _only(snap: Path, items: list[dict[str, str]]) -> None:
    document = json.loads(snap.read_text(encoding="utf-8"))
    template = document["entries"][0]
    document["entries"] = [{**template, **item} for item in items]
    snap.write_text(json.dumps(document), encoding="utf-8")


def _entries(*names: str) -> list[dict[str, str]]:
    return [{"name": n, "title": t, "date": "2026-01-01"} for n, t in (x.split("|") for x in names)]


def test_available_orders_exact_then_all_words_then_prefix_then_substring(snap: Path) -> None:
    _only(
        snap,
        _entries(
            "x_en_substringflask|Substringflask",
            "x_en_flaskprefix|Flaskprefix",
            "x_en_all_words|Python Flask Handbook",
            "devdocs_en_flask|Flask",
        ),
    )
    names = [r["name"] for r in snapshot.available("flask")["available"]]
    assert names == ["devdocs_en_flask", "x_en_all_words", "x_en_flaskprefix", "x_en_substringflask"]


def test_a_prefix_outranks_a_substring_even_when_the_substring_alias_is_shorter(snap: Path) -> None:
    _only(snap, _entries("x_en_aflas|Aflas", "x_en_flaskprefix|Flaskprefix"))
    names = [r["name"] for r in snapshot.available("flas")["available"]]
    assert names == ["x_en_flaskprefix", "x_en_aflas"]


def test_available_limit_and_empty_query(snap: Path) -> None:
    assert len(snapshot.available("docs", 2)["available"]) == 2
    assert snapshot.available("docs", 2)["matches"] > 2
    with pytest.raises(ZimloreError, match="empty query"):
        snapshot.available("  ")


def test_available_says_what_is_installed_and_which_edition(acme: Path, snap: Path) -> None:
    rows = {r["name"]: r for r in service.available("acme")["available"]}
    assert (
        rows["acme_en_widgets"]["installed"] is True and rows["acme_en_widgets"]["installed_edition"] == "2026-10-01"
    )
    assert rows["devdocs_en_acme"]["installed"] is False


def test_a_resolve_miss_carries_the_obtainable_libraries_from_the_snapshot(acme: Path, snap: Path) -> None:
    with pytest.raises(LibraryNotFound) as caught:
        service.resolve("widgetry")
    error = caught.value.as_dict()
    assert error["error"] == "no installed library matches 'widgetry'" and "primarysource zim catalog" in str(
        error["hint"]
    )
    assert error["installed"] == ["acme_en_widgets"]
    obtainable = error["obtainable"]
    assert isinstance(obtainable, list) and obtainable[0]["name"] == "devdocs_en_widgetry"
    assert obtainable[0]["install"] == "primarysource zim get devdocs_en_widgetry" and error["snapshot_age_days"] == 0
    # the other resolving paths enrich in the same way
    with pytest.raises(LibraryNotFound) as search_miss:
        service.search("anything", "widgetry")
    assert _obtainable(search_miss.value)[0]["name"] == "devdocs_en_widgetry"
    with pytest.raises(LibraryNotFound) as read_miss:
        service.read("widgetry§index")
    assert _obtainable(read_miss.value)[0]["name"] == "devdocs_en_widgetry"


def _obtainable(error: ZimloreError) -> list[dict[str, Any]]:
    found = error.extra["obtainable"]
    assert isinstance(found, list)
    return found


def test_obtainable_is_the_top_five_only(acme: Path, snap: Path) -> None:
    many = [{"name": f"devdocs_en_zork{i}", "title": f"Zork {i} Docs", "date": "2026-01-01"} for i in range(8)]
    with serve(many) as base:
        snapshot.refresh(base=base)
    with pytest.raises(LibraryNotFound) as caught:
        service.resolve("zork")
    assert len(_obtainable(caught.value)) == 5


def test_a_resolve_miss_without_a_snapshot_still_fails_the_same_way_with_a_hint(acme: Path) -> None:
    with pytest.raises(LibraryNotFound) as caught:
        service.resolve("widgetry")
    extra = caught.value.as_dict()
    assert extra["error"] == "no installed library matches 'widgetry'" and "obtainable" not in extra
    assert "primarysource zim catalog --refresh" in str(extra["snapshot_hint"])


def test_a_resolve_miss_with_a_corrupt_snapshot_still_reports_the_miss(acme: Path, snap: Path) -> None:
    snap.write_text("{broken", encoding="utf-8")
    with pytest.raises(LibraryNotFound) as caught:
        service.resolve("widgetry")
    assert "primarysource zim catalog --refresh" in str(caught.value.extra["snapshot_hint"])
    assert "obtainable" not in caught.value.extra


def test_an_empty_library_error_is_unchanged_by_the_snapshot(home: Path, snap: Path) -> None:
    with pytest.raises(ZimloreError) as caught:
        service.resolve("anything")
    assert not isinstance(caught.value, LibraryNotFound) and "obtainable" not in caught.value.extra
    assert "primarysource zim get devdocs_en_flask" in caught.value.action


def test_nothing_but_refresh_touches_the_network(
    acme: Path, snap: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the network was touched")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(catalog, "_open", forbidden)
    monkeypatch.setattr(catalog, "_get", forbidden)
    assert service.available("acme")["available"]
    with pytest.raises(LibraryNotFound) as caught:
        service.resolve("widgetry")
    assert caught.value.extra["obtainable"]
    assert cli.main(["available", "acme"]) == 0
    assert cli.main(["catalog", "--offline", "acme"]) == 0
    assert cli.main(["catalog", "--offline"]) == 0
    capsys.readouterr()
    server = contract_server()
    out = tool_text(server, "zim_available", query="acme")
    assert out.startswith("devdocs_en_acme") and "snapshot of" in out and "0 days old" in out
    miss = tool_error(server, "zim_resolve", name="widgetry")
    assert "devdocs_en_widgetry" in miss["hint"], "the offline snapshot says what could be installed"
    with pytest.raises(AssertionError, match="network"):
        snapshot.refresh()


def test_zim_available_is_listed_with_a_description_that_promises_offline(acme: Path) -> None:
    tools = anyio.run(mcp.build().list_tools)
    tool = next(t for t in tools if t.name == "zim_available")
    assert "never touches the network" in tool.description and "snapshot's age" in tool.description
    assert "zim_available" in mcp.INSTRUCTIONS


def test_zim_available_without_a_snapshot_is_an_error_object(acme: Path) -> None:
    error = tool_error(contract_server(), "zim_available", query="x")
    assert error["action"] == "primarysource zim catalog --refresh" and "acme_en_widgets" in error["error"]
    assert "ask the user" in error["hint"] and "no snapshot" in error["hint"]


def test_cli_catalog_refresh_then_offline_and_available(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with serve(CATALOGUE) as base:
        monkeypatch.setattr(catalog, "CATALOG_URL", base)
        assert cli.main(["catalog", "--refresh", "--json"]) == 0
    written = json.loads(capsys.readouterr().out)
    assert written["entries"] == 7 and written["seconds"] >= 0 and Path(written["path"]) == snapshot.path()
    assert cli.main(["available", "widgetry"]) == 0
    out = capsys.readouterr().out
    assert "primarysource zim get devdocs_en_widgetry" in out and "0 days old, offline" in out
    assert cli.main(["catalog", "--offline", "widgetry", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["available"][0]["name"] == "devdocs_en_widgetry"
    assert cli.main(["catalog", "--refresh", "--offline"]) == 2
    assert "choose one" in capsys.readouterr().err


def test_refresh_drops_entries_whose_name_could_not_be_a_safe_install_command(home: Path) -> None:
    items = [*CATALOGUE[:1], {"name": "evil;x y", "title": "Evil", "date": "2026-01-01"}]
    with serve(items) as base:
        result = snapshot.refresh(base=base)
    assert result["entries"] == 1 and [e.name for e in snapshot.load()[0]] == ["devdocs_en_acme"]


def test_cli_available_without_a_snapshot_exits_2_and_names_the_fix(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["available", "flask"]) == 2
    assert "hint: primarysource zim catalog --refresh" in capsys.readouterr().err
