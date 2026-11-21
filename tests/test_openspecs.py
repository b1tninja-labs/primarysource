"""The Open Specifications crawl, against invented tables of contents and invented pages."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.openspecs import library, sync
from primarysource.openspecs.site import ROOT_TOC, SUPPLEMENTS, doc_id, resolve, section_id
from primarysource.registry import available

ROOT = ROOT_TOC
SPEC_TOC = "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-zzz/toc.json"
MISSING_TOC = "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-yyy/toc.json"
LANDING = "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-zzz/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SECTION = "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-zzz/11111111-2222-3333-4444-555555555555"
ABSENT = "https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-yyy/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
WIDGET = b"<main><h1>1 The widget</h1><p>The widget token is aquamarine.</p></main>"
OTHER = b"<main><p>No token here.</p></main>"
HIVE_URL = SUPPLEMENTS[0].url
HIVE_ID = SUPPLEMENTS[0].doc
ENV: dict[str, str] = {}


def _toc(items: list[dict[str, str]]) -> bytes:
    return json.dumps({"items": items}).encode()


def transport(pages: dict[str, bytes]) -> Callable[[str, int], bytes]:
    def fetch(url: str, _limit: int) -> bytes:
        if url in pages:
            return pages[url]
        raise LibError(f"{url}: HTTP 404", "not a page in this test")

    return fetch


def catalog() -> dict[str, bytes]:
    return {
        ROOT: _toc(
            [
                {
                    "href": "/openspecs/windows_protocols/ms-zzz/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "toc_title": "[MS-ZZZ]: Invented protocol",
                },
                {
                    "href": "/openspecs/windows_protocols/ms-yyy/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    "toc_title": "[MS-YYY]: Absent",
                },
            ]
        ),
        SPEC_TOC: _toc(
            [
                {"href": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "toc_title": "[MS-ZZZ]: Invented protocol"},
                {"href": "11111111-2222-3333-4444-555555555555", "toc_title": "1 The widget"},
            ]
        ),
    }


def pages() -> dict[str, bytes]:
    return {**catalog(), LANDING: OTHER, SECTION: WIDGET, ABSENT: OTHER, HIVE_URL: OTHER}


def test_a_relative_href_becomes_the_en_us_page() -> None:
    page = resolve(SPEC_TOC, "11111111-2222-3333-4444-555555555555")
    assert page == SECTION
    assert resolve(ROOT, "https://example.test/other") is None
    assert doc_id(SECTION, "1 The widget") == "MS-ZZZ"
    assert section_id("1 The widget", []) == "1"
    assert section_id("1 The widget", ["1"]) == "1-2"


def test_fetch_walks_child_tables_and_records_a_missing_one(tmp_path: Path) -> None:
    fetched = sync.fetch_catalog(tmp_path, transport=transport(catalog()), environ=ENV)
    assert (fetched.documents, fetched.pages, fetched.missing) == (3, 4, 1)
    stored = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    urls = {page["url"] for page in stored["pages"]}
    assert urls == {LANDING, SECTION, ABSENT, HIVE_URL}
    assert "aquamarine" not in (tmp_path / "catalog.json").read_text(encoding="utf-8")


def test_a_dropped_connection_is_retried(tmp_path: Path) -> None:
    calls = {"spec": 0}
    body = catalog()

    def flaky(url: str, limit: int) -> bytes:
        if url == SPEC_TOC:
            calls["spec"] += 1
            if calls["spec"] == 1:
                raise LibError(f"{url}: [WinError 10054] An existing connection was forcibly closed", "retry")
        return transport(body)(url, limit)

    fetched = sync.fetch_catalog(tmp_path, transport=flaky, environ=ENV)
    assert calls["spec"] == 2
    assert fetched.missing == 1
    stored = json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))
    assert SECTION in {page["url"] for page in stored["pages"]}
    assert not (tmp_path / "crawl.json").is_file()


def test_a_missing_root_table_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="HTTP 404"):
        sync.fetch_catalog(tmp_path, transport=transport({}), environ=ENV)
    with pytest.raises(LibError, match="HTTP 404"):
        sync.fetch_catalog(tmp_path, transport=transport({}), environ=ENV)


def test_sync_indexes_a_page_and_a_second_sync_does_not_fetch_it(tmp_path: Path) -> None:
    body = pages()
    sync.fetch_catalog(tmp_path, transport=transport(body), environ=ENV)
    calls: list[str] = []

    def counting(url: str, limit: int) -> bytes:
        calls.append(url)
        return transport(body)(url, limit)

    rows = sync.sync_pages(tmp_path, transport=counting, environ=ENV)
    assert {row.doc for row in rows} == {"MS-ZZZ", "MS-YYY", HIVE_ID}
    assert SECTION in calls
    assert HIVE_URL in calls
    found = library.search("aquamarine", tmp_path)
    assert "openspecs:MS-ZZZ§1:" in found
    assert "MS-YYY" not in found
    calls.clear()
    again = sync.sync_pages(tmp_path, transport=counting, environ=ENV)
    assert calls == []
    assert all(row.skipped for row in again)
    text = library.read("ms-zzz§1", tmp_path)
    assert "aquamarine" in text
    assert "unit: block" in text
    cited = library.cite("openspecs:MS-ZZZ§1¶1", tmp_path)
    assert "span: sha256:" in cited


def test_a_learn_article_outside_the_toc_is_chaptered(tmp_path: Path) -> None:
    hive = (
        b"<main><h2>Bins</h2><p>The marker regf sits beside the marker hbin.</p>"
        b"<h2>Other</h2><p>The stone is quartzite.</p></main>"
    )
    body = {**pages(), HIVE_URL: hive}
    sync.fetch_catalog(tmp_path, transport=transport(body), environ=ENV)
    sync.sync_pages(tmp_path, [HIVE_ID], transport=transport(body), environ=ENV)
    bins = library.search("regf", tmp_path)
    assert f"openspecs:{HIVE_ID}§bins:" in bins
    assert "quartzite" not in bins
    hbin = library.search("hbin", tmp_path)
    assert f"openspecs:{HIVE_ID}§bins:" in hbin
    other = library.search("quartzite", tmp_path)
    assert f"openspecs:{HIVE_ID}§other:" in other
    assert "regf" not in other


def test_sync_without_a_catalog_names_fetch(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no Open Specifications catalog") as caught:
        sync.sync_pages(tmp_path, environ=ENV)
    assert caught.value.action == "primarysource openspecs fetch"


def test_an_unknown_specification_is_refused(tmp_path: Path) -> None:
    sync.fetch_catalog(tmp_path, transport=transport(catalog()), environ=ENV)
    with pytest.raises(LibError, match="not in the catalog"):
        sync.sync_pages(tmp_path, ["MS-NONE"], transport=transport(pages()), environ=ENV)


def test_the_fetch_command_prints_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(library, "default_home", lambda: tmp_path)

    def fake(home: Path) -> sync.FetchResult:
        assert home == tmp_path
        return sync.FetchResult(home / "catalog.json", 2, 3, 2, 1)

    monkeypatch.setattr(sync, "fetch_catalog", fake)
    assert library.default_home() == tmp_path
    from primarysource.openspecs import cli

    assert cli.main(["fetch"]) == 0
    assert (
        capsys.readouterr().out
        == "2 documents, 3 pages, 2 tables of contents, 1 missing, " + str(tmp_path / "catalog.json") + "\n"
    )


def test_openspecs_is_a_collection() -> None:
    assert "openspecs" in available()
