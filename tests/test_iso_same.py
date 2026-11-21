"""A missing ISO standard names an Ecma edition whose page states the two are the same text.

The catalogue pin is the real one (ECMA-35 and ISO/IEC 2022:1994). The homes are temporary, so the test does
not read either library.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from primarysource.errors import LibError
from primarysource.iso import library


def _iso(tmp_path: Path, documents: dict[str, object] | None = None) -> Path:
    home = tmp_path / "iso"
    home.mkdir()
    if documents is not None:
        (home / "install.json").write_text(json.dumps({"documents": documents}), encoding="utf-8")
    return home


def _ecma(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, imported: bool) -> None:
    home = tmp_path / "ecma"
    home.mkdir()
    editions = {"35-6": {"sha256": "ab" * 32}} if imported else {}
    (home / "install.json").write_text(json.dumps({"editions": editions}), encoding="utf-8")
    monkeypatch.setattr(library, "collection_home", lambda name: home)


def test_a_missing_standard_names_the_imported_identical_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ecma(tmp_path, monkeypatch, imported=True)
    with pytest.raises(LibError, match="imported as ecma:35@6") as raised:
        library.read("ISO/IEC 2022:1994", home=_iso(tmp_path))
    assert raised.value.hint == "ecma_read ecma:35@6"
    assert raised.value.action == ""
    assert "ISO/IEC 2022:1994" in raised.value.message


def test_a_missing_standard_names_the_import_command_when_the_edition_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ecma(tmp_path, monkeypatch, imported=False)
    with pytest.raises(LibError, match="ECMA-35") as raised:
        library.read("2022", home=_iso(tmp_path))
    assert raised.value.hint == "ecma_docs lists the catalogue"
    assert raised.value.action == "primarysource ecma import 35"
    assert "ecma:35@6" not in raised.value.message


def test_a_different_year_and_an_unrelated_number_stay_ordinary_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ecma(tmp_path, monkeypatch, imported=True)
    home = _iso(tmp_path)
    with pytest.raises(LibError, match=r"ISO 2022@1995 is not imported \(have:") as raised:
        library.read("2022@1995", home=home)
    assert raised.value.hint == "iso_docs lists what is imported"
    with pytest.raises(LibError, match=r"ISO 1234 is not imported \(have:") as other:
        library.read("1234§1", home=home)
    assert "Ecma" not in other.value.message


def test_an_empty_library_search_for_the_standard_names_the_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ecma(tmp_path, monkeypatch, imported=True)
    home = _iso(tmp_path)
    with pytest.raises(LibError, match="no ISO standards are imported") as raised:
        library.search("ISO/IEC 2022:1994", home=home)
    assert raised.value.hint == "ecma_read ecma:35@6"
    with pytest.raises(LibError, match="no ISO standards are imported") as plain:
        library.search("gasket", home=home)
    assert plain.value.hint == "iso_docs lists what is imported"
    assert "primarysource iso import" in plain.value.action


def test_a_search_with_no_hits_names_the_edition_and_a_word_search_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ecma(tmp_path, monkeypatch, imported=True)
    home = _iso(tmp_path, {"9999@2024": {}})

    class _Conn:
        def close(self) -> None:
            return None

    monkeypatch.setattr("primarysource.iso.library.index.open_read", lambda *_args, **_kwargs: _Conn())
    monkeypatch.setattr(
        "primarysource.iso.library.index.search",
        lambda *_args, **_kwargs: type("Found", (), {"hits": [], "relaxed": False})(),
    )
    text = library.search("2022", home=home)
    assert text.startswith("no matches")
    assert "ecma:35@6" in text and "ecma_read ecma:35@6" in text
    plain = library.search("gasket", home=home)
    assert plain.startswith("no matches")
    assert "ecma:" not in plain


def test_a_designation_search_that_hits_other_standards_still_names_the_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ecma(tmp_path, monkeypatch, imported=True)
    home = _iso(tmp_path, {"9999@2024": {}})

    class _Hit:
        doc_id = "9999@2024"
        section_id = "1"
        title = "Invented"
        snippet = "mentions the number only"

    class _Conn:
        def close(self) -> None:
            return None

    monkeypatch.setattr("primarysource.iso.library.index.open_read", lambda *_args, **_kwargs: _Conn())
    monkeypatch.setattr(
        "primarysource.iso.library.index.search",
        lambda *_args, **_kwargs: type("Found", (), {"hits": [_Hit()], "relaxed": False})(),
    )
    text = library.search("ISO/IEC 2022:1994", home=home)
    assert text.startswith("iso:9999@2024§1")
    assert "same text: ecma:35@6" in text
    bare = library.search("2022", home=home)
    assert "same text:" not in bare


def test_docs_lists_the_identical_edition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ecma(tmp_path, monkeypatch, imported=True)
    listed = library.docs(
        home=_iso(tmp_path, {"9999@2024": {"designation": "ISO 9999:2024", "title": "Invented", "source": ""}})
    )
    assert "same text  ecma:35@6  ISO/IEC 2022:1994  (imported; ecma_read ecma:35@6)" in listed
