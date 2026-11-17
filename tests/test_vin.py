"""vin: recognising a GM Part 565 filing, importing it by page, and reading it back.

The PDFs are invented. No filing text and no vehicle identifier is used.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pdffixture import make_pdf, standard

from primarysource import cli, registry
from primarysource.errors import LibError
from primarysource.identify import Probe
from primarysource.vin import VIN, library
from primarysource.vin.identify import identify
from primarysource.vin.importer import EXTRACTED, INDEX_FILE, import_file, import_folder, read_record

pytest.importorskip("pypdf")

COVER = [
    "Example Motors LLC",
    "Vehicle Identification Numbering (VIN) Standard for the 2099 Model",
    "Year is submitted per 49 CFR Part",
    "565.16(c).",
]
MODEL = ["Widget Roadster", "The Widget Roadster is a passenger car in this invented table."]
PDF = make_pdf([COVER, MODEL], [], title="Invented filing 2099")
ISO_PDF, _ISO_IDS = standard()


def _drop(home: Path, name: str = "gm-vin-2099.pdf", data: bytes = PDF) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / name
    path.write_bytes(data)
    return path


def test_a_cover_that_states_the_standard_and_cites_part_565_is_a_gm_filing() -> None:
    wrapped = Probe(
        "gm-vin-2099.pdf",
        "",
        ("\n".join(COVER),),
    )
    found = identify(wrapped)
    assert len(found) == 1
    assert found[0].collection == "vin"
    assert found[0].designation == "GM VIN standard 2099"
    assert found[0].score >= 3
    assert "49 CFR Part 565" in found[0].evidence
    assert "3779" not in found[0].designation
    renamed = Probe("letter.pdf", "", ("General Motors\n" + "\n".join(COVER[1:]),))
    assert identify(renamed)[0].designation == "GM VIN standard 2099"
    assert identify(Probe("gm-vin-2099.pdf", "", ("notes about widgets",))) == []
    assert identify(Probe("iso3779.pdf", "", ("ISO 3779:2009",))) == []


def test_the_folder_import_stores_an_extraction_and_does_not_copy_the_pdf(tmp_path: Path) -> None:
    home = tmp_path / "vin"
    _drop(home)
    done, skipped = import_folder(home)
    assert skipped == []
    assert [(item.doc, item.sections, item.segmenter) for item in done] == [("gm-vin-2099", 2, "pages")]
    entry = read_record(home)["documents"]["gm-vin-2099"]
    assert entry["label"] == "GM VIN standard 2099"
    assert entry["segmenter"] == "pages"
    stored = json.loads((home / EXTRACTED / "gm-vin-2099.json").read_text(encoding="utf-8"))
    assert [section["id"] for section in stored["sections"]] == ["1", "2"]
    assert (home / INDEX_FILE).is_file()
    copies = [path for path in home.rglob("*") if path.is_file() and path.read_bytes() == PDF]
    assert copies == [home / "gm-vin-2099.pdf"]


def test_a_second_import_skips_an_unchanged_file_and_refuses_another_collections_pdf(tmp_path: Path) -> None:
    home = tmp_path / "vin"
    _drop(home)
    import_folder(home)
    _drop(home, "ISO_IEC_9999_2024(en).pdf", ISO_PDF)
    _drop(home, "notes.pdf", b"not a pdf")
    done, skipped = import_folder(home)
    assert done == []
    reasons = dict(skipped)
    assert reasons["gm-vin-2099.pdf"] == "already imported, unchanged"
    assert "iso" in reasons["ISO_IEC_9999_2024(en).pdf"]
    assert "not a PDF" in reasons["notes.pdf"]


def test_a_missing_folder_names_the_vin_home(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="does not exist") as raised:
        import_folder(tmp_path / "vin")
    assert "PRIMARYSOURCE_VIN_HOME" in raised.value.action


def test_read_and_search_use_the_page_ref(tmp_path: Path) -> None:
    home = tmp_path / "vin"
    _drop(home)
    import_file(home, home / "gm-vin-2099.pdf")
    text = library.read("vin:gm-vin-2099§2", home=home)
    assert "Widget Roadster" in text
    assert "cite: GM VIN standard 2099, 49 CFR Part 565.16(c), §2" in text
    assert "3779" not in text
    found = library.search("Widget Roadster", home=home)
    assert found.splitlines()[0].startswith("vin:gm-vin-2099§2")
    assert "Widget Roadster" in found
    assert "(source unchanged)" in library.docs(home=home)


def test_search_reads_the_index_and_a_missing_filing_names_the_import(tmp_path: Path) -> None:
    home = tmp_path / "vin"
    _drop(home)
    import_folder(home)
    (home / EXTRACTED / "gm-vin-2099.json").unlink()
    assert library.search("Widget", home=home).startswith("vin:gm-vin-2099§")
    with pytest.raises(LibError, match="gm-vin-1999 is not imported") as raised:
        library.read("gm-vin-1999§1", home=home)
    assert "primarysource vin import" in raised.value.action


def test_the_collection_is_registered() -> None:
    assert "vin" in registry.available()
    loaded = registry.load("vin")
    assert loaded is VIN and loaded.prefix == "vin_"
    assert loaded.identify == "primarysource.vin.identify:identify"


def test_the_command_imports_and_searches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_VIN_HOME", str(tmp_path / "shelf"))
    _drop(tmp_path / "shelf")
    assert cli.main(["vin", "import"]) == 0
    assert "imported vin:gm-vin-2099 (GM VIN standard 2099)" in capsys.readouterr().out
    assert cli.main(["vin", "search", "Widget Roadster"]) == 0
    assert "vin:gm-vin-2099§2" in capsys.readouterr().out
    assert cli.main(["vin", "read", "gm-vin-2099§9"]) == 1
    assert "hint:" in capsys.readouterr().err


def test_the_server_serves_three_prefixed_text_tools(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    home = tmp_path / "vin"
    _drop(home)
    import_folder(home)
    from primarysource.vin.server import server

    assert [tool.name for tool in asyncio.run(server.list_tools())] == ["vin_read", "vin_search", "vin_docs"]
