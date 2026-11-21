"""The Bluetooth catalog: one invented specification, and a book link that tries to leave its directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from primarysource.bluetooth import library, sync
from primarysource.bluetooth.book import parts
from primarysource.bluetooth.catalogue import LISTING, book_url, parse_listing
from primarysource.errors import LibError

PAGE = "https://www.bluetooth.com/specifications/specs/gasket-service/"
BOOK = "https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/GASKET/out/en/index-en.html"
LISTING_HTML = f"""
<table><tr id="post-1" class="index-item spec-status-adopted">
<td class="title"><a href="{PAGE}">Gasket Service</a></td>
<td class="revision">1.0</td>
<td class="type">Specification</td>
<td class="status">Adopted</td>
</tr></table>
"""
PAGE_HTML = (
    '<a href="https://www.bluetooth.com/specifications/specs/html/?src=GASKET/out/en/index-en.html">'
    "Gasket Service (HTML)</a>"
)
BOOK_HTML = """
<html><body>
<div id="toc-wrapper"><a href="../secret.html" data-topic-level="1">Secret</a></div>
<div id="content-wrapper">
<h1>Gasket Service</h1>
<h2>1. Introduction</h2>
<p>A gasket holds the sprocket.</p>
</div>
</body></html>
"""


def _transport(url: str, _limit: int) -> bytes:
    if url == LISTING:
        return LISTING_HTML.encode()
    if url == PAGE:
        return PAGE_HTML.encode()
    if url == BOOK:
        return BOOK_HTML.encode()
    raise AssertionError(url)


def test_the_catalog_row_keeps_the_version_and_status() -> None:
    specs = parse_listing(LISTING_HTML)
    assert [(item.doc, item.version, item.status, item.page) for item in specs] == [
        ("gasket-service", "1.0", "Adopted", PAGE)
    ]
    with pytest.raises(LibError, match="no catalog rows"):
        parse_listing("<p>empty</p>")


def test_the_html_book_is_the_specification_and_a_foreign_link_is_not() -> None:
    assert book_url(PAGE_HTML, PAGE) == BOOK
    assert book_url('<a href="https://evil.example/index-en.html">PDF</a>', PAGE) is None


def test_a_book_link_that_escapes_its_directory_is_dropped() -> None:
    found = parts(BOOK_HTML, BOOK)
    assert [item.path for item in found] == ["index-en.html"]
    assert all("secret" not in item.url for item in found)


def test_a_book_is_indexed_and_a_second_sync_skips_it(tmp_path: Path) -> None:
    done = sync.sync_books(tmp_path, transport=_transport)
    assert [(item.doc, item.sections, item.skipped) for item in done] == [("gasket-service", 2, False)]
    assert not (tmp_path / "secret.html").exists()
    library.build_index(tmp_path)
    assert "bluetooth:gasket-service§1" in library.search("gasket", home=tmp_path)
    cited = library.cite("gasket-service§1", home=tmp_path)
    assert cited.startswith("bluetooth:gasket-service§1")
    assert "Gasket Service" in cited
    again = sync.sync_books(tmp_path, transport=_transport)
    assert again[0].skipped
