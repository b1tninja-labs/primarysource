"""sae: an invented bookmarked PDF, imported by its file name. No SAE text."""

from __future__ import annotations

from pathlib import Path

import pytest
from pdffixture import standard

from primarysource.errors import LibError
from primarysource.sae import library
from primarysource.sae.designation import from_filename, parse
from primarysource.sae.importer import import_file

pytest.importorskip("pypdf")

PDF, IDS = standard()


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


def test_a_printed_designation_and_the_file_name_agree() -> None:
    found = parse("SAE J2534:2002")
    assert (found.label, found.doc, found.key) == ("SAE J2534:2002", "j2534@2002", "j2534_2002")
    named = from_filename("sae.j2534.2002.pdf")
    assert named is not None and named.doc == found.doc
    part = parse("SAE J2534-1:2004")
    assert part.doc == "j2534-1@2004"


def test_a_scan_is_read_by_the_supplied_ocr_and_not_by_copying_the_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "sae"
    source = tmp_path / "research" / "sae.j2534.1999.pdf"
    source.parent.mkdir()
    source.write_bytes(PDF)

    def explode(_data: bytes, _path: Path, *, numbered: bool = False) -> dict[str, object]:
        raise LibError("the PDF has no bookmarks", "")

    monkeypatch.setattr("primarysource.readers.pdf.extract", explode)
    result = import_file(home, source, ocr=lambda _path: ["A gasket is a seal."] * 3)
    assert result.segmenter == "tesseract"
    assert "gasket" in library.search("gasket", home=home).lower()


def test_the_import_indexes_the_invented_standard_and_does_not_copy_the_pdf(tmp_path: Path) -> None:
    home = tmp_path / "sae"
    source = tmp_path / "research" / "sae.j2534.2002.pdf"
    source.parent.mkdir()
    source.write_bytes(PDF)
    result = import_file(home, source)
    assert result.doc == "j2534@2002"
    assert result.sections == len(IDS)
    assert not (home / "sae.j2534.2002.pdf").exists()
    assert "gasket" in library.search("gasket", home=home).lower()
    text = library.read("sae:j2534@2002§1", home=home)
    assert "widget protocol" in text
    assert "SAE J2534:2002" in library.cite("j2534@2002§1", home=home)
