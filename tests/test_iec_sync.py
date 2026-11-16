"""IEC free-stub listing and sync record helpers (no live webstore)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from primarysource.errors import LibError
from primarysource.iec import sync
from primarysource.iec.webstore import Webstore
from primarysource.registry import available, load


def _stub(path: Path, *, pub_id: str, reference: str, head: str, free: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "id": pub_id,
                "reference": reference,
                "title": reference,
                "head": head,
                "is_free": free,
            }
        ),
        encoding="utf-8",
    )


def test_iec_is_registered_and_its_cli_loads() -> None:
    assert "iec" in available()
    collection = load("iec")
    assert collection.name == "iec"
    assert collection.cli.endswith(":main")


def test_free_from_stubs_keeps_only_free_and_names_pdfs(tmp_path: Path) -> None:
    stubs = tmp_path / "webstore" / "stubs"
    stubs.mkdir(parents=True)
    _stub(stubs / "1.json", pub_id="1", reference="ISO/IEC TR 1:2000", head="ISO/IEC", free=True)
    _stub(stubs / "2.json", pub_id="2", reference="IEC 60000", head="IEC", free=False)
    _stub(stubs / "3.json", pub_id="3", reference="IEC ACEE 01:2018", head="IEC", free=True)
    pubs = sync.free_from_stubs(stubs)
    assert [p.publication_id for p in pubs] == ["1", "3"]
    assert sync.pdf_name("ISO/IEC TR 1:2000", "1") == "ISO_IEC_TR_1_2000.pdf"


def test_sync_skips_existing_pdf_and_mirrors_iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "iec"
    stubs = home / "webstore" / "stubs"
    stubs.mkdir(parents=True)
    pdfs = home / "pdfs"
    pdfs.mkdir()
    iso_home = tmp_path / "iso"
    iso_home.mkdir()
    _stub(stubs / "10.json", pub_id="10", reference="ISO/IEC TR 10:2000", head="ISO/IEC")
    existing = pdfs / "ISO_IEC_TR_10_2000.pdf"
    existing.write_bytes(b"%PDF-1.4 " + b"x" * 2000)

    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    monkeypatch.setenv("IEC_EMAIL", "buyer@example.com")
    monkeypatch.setenv("IEC_PASSWORD", "secret")

    class FakeStore:
        def __init__(self, email: str, password: str) -> None:
            assert email == "buyer@example.com"

        def login_html(self) -> None:
            return None

        def library_order_items(self, *, login: bool = True) -> list[tuple[str, str, str]]:
            return []

        def order_free_batch(self, publication_ids: list[str]) -> tuple[str, list[str]]:
            raise AssertionError("should not order when the PDF is already on disk")

    monkeypatch.setattr(sync, "Webstore", FakeStore)
    results = sync.sync_free(home)
    assert len(results) == 1
    assert results[0].skipped is True
    assert (iso_home / existing.name).is_file()


def test_sync_orders_and_downloads_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "iec"
    stubs = home / "webstore" / "stubs"
    stubs.mkdir(parents=True)
    _stub(stubs / "20.json", pub_id="20", reference="IEC ACEE 01:2018", head="IEC")
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    monkeypatch.setenv("IEC_EMAIL", "buyer@example.com")
    monkeypatch.setenv("IEC_PASSWORD", "secret")

    class FakeStore:
        def __init__(self, email: str, password: str) -> None:
            self.owned: dict[str, str] = {}

        def login_html(self) -> None:
            return None

        def library_order_items(self, *, login: bool = True) -> list[tuple[str, str, str]]:
            return [(item, ref, "") for ref, item in self.owned.items()]

        def order_free_batch(self, publication_ids: list[str]) -> tuple[str, list[str]]:
            assert publication_ids == ["20"]
            self.owned["iec acee 01:2018"] = "item-99"
            return "order-1", []

        def fetch_pdf(self, order_item_id: str, dest: Path, *, waits: int = 12, interval: float = 5.0) -> int:
            assert order_item_id == "item-99"
            dest.parent.mkdir(parents=True, exist_ok=True)
            body = b"%PDF-1.4 " + b"y" * 1500
            dest.write_bytes(body)
            return len(body)

    monkeypatch.setattr(sync, "Webstore", FakeStore)
    results = sync.sync_free(home)
    assert len(results) == 1
    assert results[0].skipped is False
    assert results[0].order_item_id == "item-99"
    assert results[0].path.is_file()
    record = sync.read_record(home)
    assert record["20"]["order_item_id"] == "item-99"


def test_credentials_missing_names_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "iec"
    stubs = home / "webstore" / "stubs"
    stubs.mkdir(parents=True)
    _stub(stubs / "1.json", pub_id="1", reference="IEC 1", head="IEC")
    monkeypatch.delenv("IEC_EMAIL", raising=False)
    monkeypatch.delenv("IEC_PASSWORD", raising=False)
    with pytest.raises(LibError) as raised:
        sync.sync_free(home)
    assert "IEC_EMAIL" in raised.value.action


def test_a_downloaded_zip_keeps_its_pdf_and_its_nested_files(tmp_path: Path) -> None:
    import zipfile

    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zipped:
        zipped.writestr("sample.c", "int value;\n")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zipped:
        zipped.write(inner, "sample.zip")
        zipped.writestr("doc.pdf", b"%PDF-1.4\n" + b"x" * 1200)
    home = tmp_path / "iec"
    saved = home / "pdfs" / "IEC_1.zip"
    saved.parent.mkdir(parents=True)
    saved.write_bytes(outer.read_bytes())
    extra = sync.keep_related(home, saved)
    artifact = home / "artifacts" / "IEC_1"
    assert (artifact / "doc.pdf").is_file()
    assert (artifact / "sample.zip").is_file()
    assert (artifact / "sample" / "sample.c").read_text(encoding="utf-8") == "int value;\n"
    assert (home / "pdfs" / "IEC_1.pdf").is_file()
    assert saved.is_file()
    assert extra["artifacts"] == "artifacts/IEC_1"
    assert extra["pdf"] == "pdfs/IEC_1.pdf"


def test_select_option_reads_the_labelled_choice() -> None:
    from primarysource.iec.webstore import _select_option

    text = (
        '<select name="options[publication_format]">'
        '<option value="">-- Please select --</option>'
        '<option value="52">Electronic</option>'
        '<option value="46">Hardcopy</option>'
        "</select>"
    )
    assert _select_option(text, "options[publication_format]", "Electronic") == "52"
    bilingual = (
        '<select name="options[publication_language]">'
        '<option value="">-- Please select --</option>'
        '<option value="28">English/French</option>'
        "</select>"
    )
    assert _select_option(bilingual, "options[publication_language]", "English", contains=True) == "28"


def test_electronic_follows_the_language_when_two_formats_share_a_title() -> None:
    from primarysource.iec.webstore import _electronic_for_language

    text = """
    <select name="options[publication_language]">
      <option value="13">English</option>
      <option value="16">French</option>
    </select>
    <select name="options[publication_format]">
      <option value="37" data-languages="fr" data-option-code="PDF">Electronic</option>
      <option value="52" data-languages="en" data-option-code="ANY">Electronic</option>
    </select>
    """
    assert _electronic_for_language(text, "13") == "52"


def test_next_page_is_the_action_link_not_the_jump() -> None:
    from primarysource.iec.webstore import _next_page

    text = (
        '<a href="https://webstore.iec.ch/en/publication/customer/products/?p=8" '
        'class="page next jump">8</a>'
        '<a href="https://webstore.iec.ch/en/publication/customer/products/?p=2" '
        'class="action next" aria-label="Next">'
    )
    assert _next_page(text) == "https://webstore.iec.ch/en/publication/customer/products/?p=2"


def test_form_key_and_multipart_helpers() -> None:
    page = b'<input name="form_key" type="hidden" value="abc123" />'
    from primarysource.iec import webstore

    assert webstore._form_key(page) == "abc123"
    body, ctype = webstore._multipart({"a": "1", "b": "2"})
    assert "multipart/form-data" in ctype
    assert b'name="a"' in body and b"1" in body


def test_download_status_unwraps_double_encoded_json(monkeypatch: pytest.MonkeyPatch) -> None:
    store = Webstore("a@b.c", "pw")

    def fake_request(*_a: Any, **_k: Any) -> tuple[int, dict[str, str], bytes, str]:
        payload = json.dumps({"is_downloadable": True, "download_url": "https://example/x.pdf"})
        return 200, {}, json.dumps(payload).encode(), "https://webstore.iec.ch/"

    monkeypatch.setattr(store, "request", fake_request)
    data = store.download_status("123")
    assert data["is_downloadable"] is True
