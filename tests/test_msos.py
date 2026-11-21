"""Open Specifications: the zip link on a set's page, and indexing one invented PDF from that zip."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from pdffixture import standard

from primarysource.errors import LibError
from primarysource.msos import importer, library, sync
from primarysource.msos.catalogue import PROTOCOLS

pytest.importorskip("pypdf")

PAGE = PROTOCOLS
ZIP = "https://download.microsoft.com/test/Exchange_Protocols.zip"
HTML = (
    f'<a href="{ZIP}">Exchange Server Protocols .zip file</a>'
    '<a href="https://download.microsoft.com/test/other.zip">Some other .zip file</a>'
)


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


def _zip() -> bytes:
    pdf, _ids = standard()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[MS-TEST].pdf", pdf)
        archive.writestr("../[MS-EVIL].pdf", pdf)
    return buffer.getvalue()


def _transport(page: str, blob: bytes) -> sync.Transport:
    def transport(url: str, _limit: int) -> bytes:
        if url == page:
            return HTML.encode()
        if url == ZIP:
            return blob
        raise AssertionError(url)

    return transport


def test_the_zip_link_is_the_anchor_that_names_the_set() -> None:
    assert sync.zip_link(HTML, "Exchange Server Protocols", PAGE) == ZIP
    with pytest.raises(LibError, match="no zip link"):
        sync.zip_link(HTML, "Windows Protocols", PAGE)


def test_a_dead_fwlink_falls_back_to_the_published_zip() -> None:
    direct = "https://sqlprotocoldoc.z19.web.core.windows.net/SQLServerProtocols.zip"
    live = "https://winprotocoldoc.z19.web.core.windows.net/Windows_Protocols.zip"
    assert sync.choose(live, direct) == live
    assert sync.choose("https://www.bing.com/?ref=go&linkid=120223", direct) == direct
    with pytest.raises(LibError, match="not a zip"):
        sync.choose("https://www.bing.com/?ref=go&linkid=120223", "")


def test_a_foreign_host_is_refused() -> None:
    with pytest.raises(LibError, match="refusing to fetch"):
        sync.resolve("https://evil.example/spec.zip")


WIM = (
    b"{\\rtf1\\ansi"
    b"{\\stylesheet{\\s1\\outlinelevel0 heading 1;}}"
    b"\\pard\\plain\\outlinelevel0 2 Resource compression\\par"
    b"\\pard\\plain A resource chunk uses the quartz token.\\par"
    b"}"
)


def test_an_rtf_outline_is_a_section() -> None:
    from primarysource.readers import rtf

    extracted = rtf.extract(WIM)
    assert extracted["segmenter"] == "outline"
    assert extracted["sections"][0]["id"] == "2"
    assert extracted["sections"][0]["title"] == "Resource compression"
    assert "quartz token" in extracted["sections"][0]["text"]
    styled = b"{\\rtf1{\\stylesheet{\\s1\\outlinelevel0 heading 1;}}\\pard\\plain No heading here.\\par}"
    with pytest.raises(LibError, match="no outline headings"):
        rtf.extract(styled)


def test_the_wim_paper_is_imported_from_its_download(tmp_path: Path) -> None:
    def transport(url: str, _limit: int) -> bytes:
        assert url == sync.WIM_URL
        return WIM

    fetched = sync.sync_sets(tmp_path, ["wim"], transport=transport)
    assert [item.set_id for item in fetched] == ["wim"]
    assert (tmp_path / "wim" / "Windows Imaging File Format.rtf").read_bytes() == WIM
    done, skipped = importer.import_zips(tmp_path, ["wim"])
    assert [(item.doc, item.sections) for item in done] == [("ms-wim", 1)]
    assert skipped == []
    found = library.search("resource compression", home=tmp_path)
    assert "msos:ms-wim§2" in found
    assert "quartz" in library.search("quartz", home=tmp_path)
    again, _skipped = importer.import_zips(tmp_path, ["wim"])
    assert again == []


def test_a_zip_member_is_indexed_and_a_path_that_escapes_is_skipped(tmp_path: Path) -> None:
    blob = _zip()
    results = sync.sync_sets(tmp_path, ["exchange"], transport=_transport(PAGE, blob))
    assert [item.set_id for item in results] == ["exchange"]
    assert (tmp_path / "zips" / "exchange.zip").is_file()
    done, skipped = importer.import_zips(tmp_path)
    assert [item.doc for item in done] == ["ms-test"]
    assert skipped == []
    assert "msos:ms-test§2.1" in library.search("gasket", home=tmp_path)
    cited = library.cite("[MS-TEST]§2.1", home=tmp_path)
    assert cited.startswith("msos:ms-test§2.1")
    assert "[MS-TEST]" in cited
    assert not (tmp_path / "[MS-EVIL].pdf").exists()
