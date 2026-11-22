"""sae: the file-name rules, the gate and an import of an invented PDF named like a J2735 download.

The PDF is `pdffixture.standard()`, an invented standard; no SAE text is used anywhere. The terms variable is set only
with `monkeypatch`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pdffixture import standard

from primarysource import registry, terms
from primarysource.errors import LibError
from primarysource.localpdf import store
from primarysource.localpdf.store import read_record
from primarysource.sae import SPEC, name_file

pytest.importorskip("pypdf")

PDF, IDS = standard()
VAR = "PRIMARYSOURCE_SAE_ACCEPT_TERMS"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)
    monkeypatch.delenv(VAR, raising=False)


def test_two_known_names_are_recognised_and_everything_else_is_left_alone() -> None:
    j2735 = name_file("J2735_V201603.pdf", "")
    j1979 = name_file("sae.j1979.2002.pdf", "")
    assert j2735 is not None and j2735.doc == "j2735-201603"
    assert j1979 is not None and j1979.doc == "j1979-2002"
    assert name_file("Event Data Recorder(SAE J1698).pdf", "") is None
    assert name_file("SAE J2534 API REFERENCE.pdf", "") is None


def test_import_is_refused_without_the_variable_and_names_no_url(tmp_path: Path) -> None:
    (tmp_path / "J2735_V201603.pdf").write_bytes(PDF)
    with pytest.raises(LibError, match=VAR) as raised:
        store.import_folder(SPEC, tmp_path)
    assert "SAE International" in raised.value.as_text() and "http" not in raised.value.as_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["J2735_V201603.pdf"]


def test_the_import_records_the_acknowledgement_and_skips_an_unknown_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAR, "1")
    (tmp_path / "J2735_V201603.pdf").write_bytes(PDF)
    (tmp_path / "other.pdf").write_bytes(PDF)
    done, skipped = store.import_folder(SPEC, tmp_path)
    assert [r.doc for r in done] == ["j2735-201603"]
    assert any(name == "other.pdf" for name, _why in skipped)
    assert list(read_record(tmp_path)[terms.RECORD_KEY]["documents"]) == ["j2735-201603"]


def test_the_collection_is_registered() -> None:
    assert registry.BUILTIN["sae"].startswith("primarysource.sae:SAE")
