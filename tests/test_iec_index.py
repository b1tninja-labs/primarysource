"""IEC publications that are not ISO editions: designation, import, and search.

Every PDF is invented (`pdffixture.standard`). Nothing here reads the owner's IEC library.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pdffixture import standard

from primarysource.errors import LibError
from primarysource.identify import Probe
from primarysource.iec import importer, library
from primarysource.iec.designation import from_filename, parse
from primarysource.iec.identify import identify

pytest.importorskip("pypdf")


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)
    monkeypatch.setattr(importer, "indexed_as_iso", lambda _doc: None)


def test_designations_cover_a_standard_a_commented_version_and_an_acee_document() -> None:
    assert parse("IEC 60835-2-1:1990").doc == "60835-2-1@1990"
    assert parse("IEC CA 01:2020 CSV").doc == "ca-01@2020+csv"
    assert parse("IEC ACEE 02:2018").label == "IEC ACEE 02:2018"
    assert from_filename("IEC_CA_01_2020_CSV.pdf").doc == "ca-01@2020+csv"  # type: ignore[union-attr]
    with pytest.raises(LibError, match="not an IEC designation"):
        parse("ISO/IEC 5230:2020")


def test_an_iso_iec_cover_is_not_an_iec_document() -> None:
    probe = Probe("ISO_IEC_5230_2020.pdf", pages=("ISO/IEC 5230:2020",))
    assert identify(probe) == []
    named = Probe("IEC_60835-2-1_1990.pdf", pages=("IEC 60835-2-1:1990",))
    assert identify(named)[0].designation == "IEC 60835-2-1:1990"


def test_a_bookmarked_iec_publication_is_searchable(tmp_path: Path) -> None:
    pdf, ids = standard()
    home = tmp_path / "iec"
    path = home / "pdfs" / "IEC_9991_2024.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(pdf)
    (home / "ISO_IEC_9991_2024.pdf").write_bytes(pdf)
    done, skipped = importer.import_folder(home)
    assert [result.doc for result in done] == ["9991@2024"]
    assert skipped == [("ISO_IEC_9991_2024.pdf", "ISO publication; primarysource iso import")]
    assert done[0].sections == len(ids)
    found = library.search("gasket", home=home)
    assert found.splitlines()[0].startswith("iec:9991@2024§2.1")
    assert "IEC 9991:2024" in library.cite("IEC 9991:2024§2.1", home=home)
    assert "iec:9991@2024" in library.docs(home=home)


def test_an_edition_already_in_the_iso_index_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importer, "indexed_as_iso", lambda doc: "9991@2024" if doc == "9991@2024" else None)
    pdf, _ids = standard()
    home = tmp_path / "iec"
    path = home / "IEC_9991_2024.pdf"
    home.mkdir()
    path.write_bytes(pdf)
    with pytest.raises(LibError, match="already indexed as iso:9991@2024"):
        importer.import_file(home, path)
