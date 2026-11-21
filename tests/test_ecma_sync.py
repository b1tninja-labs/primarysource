"""ecma fetch and sync: the index captured on 2026-11-17, then the pinned editions only."""

from __future__ import annotations

from pathlib import Path

import pytest
from pdffixture import standard

from primarysource.c2sp._fetch import sha256
from primarysource.ecma import cli
from primarysource.ecma.catalogue import Catalogue, Edition, Terms
from primarysource.ecma.site import INDEX_URL, parse_standard
from primarysource.ecma.sync import FetchResult, fetch_index, sync_pinned
from primarysource.errors import LibError

pytest.importorskip("pypdf")

PDF, _IDS = standard()
PAGE = "https://ecma-international.org/publications-and-standards/standards/ecma-999/"
PDF_URL = "https://ecma-international.org/wp-content/uploads/ECMA-999_1st_edition.pdf"
WITHDRAWN = "https://www.ecma-international.org/publications-and-standards/withdrawn-standards/"

INDEX = f"""
<ul class="items-list-wrapper standards">
<li class="list-header"><span>Number</span><span>Title</span><span>Last change</span></li>
<li><span><a href="{PAGE}">ECMA-999</a></span>
<span><a href="{PAGE}">Invented standard</a></span><span>January 2026</span></li>
</ul>
<p><a href="{WITHDRAWN}">See the withdrawn Standards</a>.</p>
"""

WITHDRAWN_PAGE = """
<ul class="items-list-wrapper standards">
<li class="list-header"><span>Number</span><span>Title</span><span>Last change</span></li>
<li><span><a href="https://ecma-international.org/publications-and-standards/standards/ecma-1/">ECMA-1</a></span>
<span><a href="https://ecma-international.org/publications-and-standards/standards/ecma-1/">Invented withdrawn</a>
</span>
<span>June 1961</span></li>
</ul>
"""


def _page(pdf: str = PDF_URL) -> str:
    return f"""
<h1>ECMA-999</h1>
<p class="ecma-item-short-description">Invented standard</p>
<p class="ecma-item-edition">1st edition, January 2026</p>
<a class="bg-orange download" href="{pdf}">Download this standard</a>
<ul class="ecma-item-archives">
<li><span>ECMA-999, 2nd edition, June 2026</span>
<span><a class="orange-txt download" href="https://ecma-international.org/wp-content/uploads/ECMA-999_2nd.pdf">Download</a></span>
</li>
</ul>
"""


def _cat() -> Catalogue:
    edition = Edition(
        "999",
        1,
        "ECMA-999",
        "Invented standard",
        "1st edition, January 2026",
        PAGE,
        PDF_URL,
        len(PDF),
        sha256(PDF),
    )
    return Catalogue(
        Terms("Ecma text copyright policy", "volume", "https://example.invalid/t", "2026-11-17", "invented"),
        (edition,),
    )


def _pages(pdf: str = PDF_URL) -> dict[str, bytes]:
    return {
        INDEX_URL: INDEX.encode(),
        WITHDRAWN: WITHDRAWN_PAGE.encode(),
        PAGE: _page(pdf).encode(),
        PDF_URL: PDF,
    }


@pytest.fixture(autouse=True)
def _no_pdftotext(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.ecma._pdf.shutil.which", lambda _name: None)


def test_fetch_writes_the_index_and_the_withdrawn_list_it_links_to(tmp_path: Path) -> None:
    pages = _pages()

    def transport(url: str, max_bytes: int) -> bytes:
        assert url in pages
        return pages[url]

    result = fetch_index(tmp_path, transport=transport)
    assert (result.standards, result.withdrawn) == (1, 1)
    stored = (tmp_path / "remote.json").read_text(encoding="utf-8")
    assert "Invented standard" in stored and "Invented withdrawn" in stored
    assert "ECMA-999_1st_edition.pdf" not in stored


def test_a_standard_page_names_the_current_edition_and_its_archive() -> None:
    found = parse_standard(_page(), "999")
    current = next(row for row in found if row.current)
    archived = next(row for row in found if not row.current)
    assert (current.edition, current.source_url) == (1, PDF_URL)
    assert archived.edition == 2
    assert archived.source_url.endswith("/ECMA-999_2nd.pdf")


def test_sync_imports_a_pinned_edition_whose_page_still_serves_it(tmp_path: Path) -> None:
    pages = _pages()
    calls: list[str] = []

    def transport(url: str, max_bytes: int) -> bytes:
        calls.append(url)
        return pages[url]

    fetch_index(tmp_path, transport=transport)
    result = sync_pinned(tmp_path, transport=transport, cat=_cat())
    assert result[0].skipped is False and result[0].key == "999-1"
    assert (tmp_path / "999-1.pdf").read_bytes() == PDF
    assert calls.count(PDF_URL) == 1


def test_sync_skips_an_edition_already_imported(tmp_path: Path) -> None:
    pages = _pages()
    calls: list[str] = []

    def transport(url: str, max_bytes: int) -> bytes:
        calls.append(url)
        return pages[url]

    fetch_index(tmp_path, transport=transport)
    sync_pinned(tmp_path, transport=transport, cat=_cat())
    calls.clear()
    result = sync_pinned(tmp_path, transport=transport, cat=_cat())
    assert result[0].skipped is True
    assert PDF_URL not in calls and PAGE in calls


def test_sync_refuses_a_page_whose_pdf_url_is_not_the_pin(tmp_path: Path) -> None:
    moved = "https://ecma-international.org/wp-content/uploads/ECMA-999_moved.pdf"
    pages = _pages(moved)

    def transport(url: str, max_bytes: int) -> bytes:
        return pages[url]

    fetch_index(tmp_path, transport=transport)
    with pytest.raises(LibError, match="no longer at the pinned URL"):
        sync_pinned(tmp_path, transport=transport, cat=_cat())
    assert not list(tmp_path.glob("999-1*"))


def test_sync_without_a_fetch_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no Ecma index") as caught:
        sync_pinned(tmp_path, transport=lambda url, max_bytes: b"", cat=_cat())
    assert "ecma fetch" in caught.value.hint


def test_the_fetch_command_prints_the_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))

    def fake(home: Path) -> FetchResult:
        return FetchResult(home / "remote.json", 295, 139)

    monkeypatch.setattr(cli.sync, "fetch_index", fake)
    assert cli.main(["fetch"]) == 0
    assert capsys.readouterr().out.startswith("295 standards, 139 withdrawn,")
