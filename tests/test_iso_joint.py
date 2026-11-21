"""Free joint ISO/IEC editions: page indexing, the citation, and a zip that also holds other files.

Every PDF is invented (`pdffixture.make_pdf`). The catalogue is a temporary free-sync record, never the
owner's IEC library.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from pdffixture import make_pdf

from primarysource.errors import LibError
from primarysource.iso import importer, joint, library

pytest.importorskip("pypdf")


def _catalogue(iec: Path, reference: str, *names: str) -> None:
    iec.mkdir(parents=True, exist_ok=True)
    documents = {
        "1": {
            "reference": reference,
            "head": "ISO/IEC",
            "iso_path": names[0],
            "path": f"pdfs/{names[0]}",
        }
    }
    (iec / "free-sync.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")


def _plain(pages: list[list[str]]) -> bytes:
    return make_pdf(pages, [], title="Invented joint edition")


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


@pytest.fixture
def iec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "iec"
    monkeypatch.setattr(joint, "iec_home", lambda: home)
    return home


def test_an_unbookmarked_free_joint_edition_is_indexed_by_page(tmp_path: Path, iec: Path) -> None:
    _catalogue(iec, "ISO/IEC 9997:2024", "ISO_IEC_9997_2024.pdf")
    home = tmp_path / "iso"
    path = home / "ISO_IEC_9997_2024.pdf"
    home.mkdir()
    path.write_bytes(
        _plain(
            [
                ["Example Courier is the invented model."],
                ["The second page names the Example Courier plant."],
            ]
        )
    )
    result = importer.import_file(home, path)
    assert result.doc == "9997@2024" and result.segmenter == "pages" and result.sections == 2
    assert "indexed by page" in result.note
    found = library.search("plant", home=home)
    assert found.splitlines()[0].startswith("iso:9997@2024§2")
    assert "free joint publication" in library.docs(home=home)
    assert "free joint publication" in library.cite("9997@2024§2", home=home)


def test_an_unbookmarked_pdf_that_is_not_a_free_joint_edition_is_refused(tmp_path: Path, iec: Path) -> None:
    _catalogue(iec, "ISO/IEC 9997:2024", "ISO_IEC_9997_2024.pdf")
    home = tmp_path / "iso"
    path = home / "ISO_IEC_9996_2024.pdf"
    home.mkdir()
    path.write_bytes(_plain([["This edition is not in the free record."]]))
    with pytest.raises(LibError, match="no bookmarks"):
        importer.import_file(home, path)
    assert "9996@2024" not in importer.read_record(home)["documents"]


def test_a_missing_free_joint_edition_names_the_file_already_on_disk(tmp_path: Path, iec: Path) -> None:
    _catalogue(iec, "ISO/IEC 9994:2024", "ISO_IEC_9994_2024.pdf")
    home = tmp_path / "iso"
    home.mkdir()
    (home / "ISO_IEC_9994_2024.pdf").write_bytes(b"%PDF-1.4 unused")
    with pytest.raises(LibError, match="free joint publication ISO/IEC 9994:2024") as raised:
        library.read("9994@2024", home=home)
    assert "ISO_IEC_9994_2024.pdf" in raised.value.message
    assert raised.value.action.endswith('primarysource iso import "' + str(home / "ISO_IEC_9994_2024.pdf") + '"')


def test_a_bookmarked_edition_in_the_catalogue_keeps_its_clauses_and_is_marked_free(
    tmp_path: Path, iec: Path
) -> None:
    from pdffixture import standard

    pdf, ids = standard()
    _catalogue(iec, "ISO/IEC 9999:2024", "ISO_IEC_9999_2024(en).pdf")
    home = tmp_path / "iso"
    home.mkdir()
    (home / "ISO_IEC_9999_2024(en).pdf").write_bytes(pdf)
    result = importer.import_file(home, home / "ISO_IEC_9999_2024(en).pdf")
    assert result.segmenter == "bookmarks" and result.sections == len(ids)
    assert "free joint publication" in library.docs(home=home)
    assert "indexed by page" not in result.note


def test_a_cover_year_that_differs_from_the_catalogue_still_reads(tmp_path: Path, iec: Path) -> None:
    _catalogue(iec, "ISO/IEC TR 9998:2015", "ISO_IEC_TR_9998_2015.pdf")
    home = tmp_path / "iso"
    path = home / "ISO_IEC_TR_9998_2015.pdf"
    home.mkdir()
    path.write_bytes(_plain([["Example Courier is the invented joint edition."]]))
    result = importer.import_file(home, path, "ISO/IEC TR 9998:2016")
    assert result.doc == "9998@2016" and result.segmenter == "pages"
    text = library.read("9998@2015", home=home)
    assert "Example Courier is the invented joint edition." in text
    assert "ISO/IEC TR 9998:2016" in text
    assert "free joint publication" in text
    listed = library.docs(home=home)
    assert "iso:9998@2016" in listed and "free joint publication" in listed


def test_a_zip_contributes_its_joint_edition_and_leaves_the_other_member(tmp_path: Path, iec: Path) -> None:
    _catalogue(iec, "ISO/IEC 9995:2024", "ISO_IEC_9995_2024.zip")
    home = tmp_path / "iso"
    home.mkdir()
    edition = _plain([["Example Courier is printed on the joint edition."]])
    other = _plain([["Unrelated supplement mentions a spare gasket."]])
    with zipfile.ZipFile(home / "ISO_IEC_9995_2024.zip", "w") as archive:
        archive.writestr("ISO_IEC_9995_2024.pdf", edition)
        archive.writestr("supplement.pdf", other)
        archive.writestr("../escape.pdf", edition)
    done, skipped = importer.import_folder(home)
    assert [result.doc for result in done] == ["9995@2024"]
    assert not any("escape" in name for name, _why in skipped)
    text = library.search("Courier", home=home)
    assert "iso:9995@2024§1" in text
    assert library.search("gasket", home=home).startswith("no matches")
    assert (home / "ISO_IEC_9995_2024.pdf").is_file()
    assert not (home / "supplement.pdf").exists()
    assert not (home / "escape.pdf").exists()
