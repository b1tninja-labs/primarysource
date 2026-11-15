"""can: the file name, the gated import of a bookmarked specification, sentence-unit reading and the CLI.

The PDF is `pdffixture.standard()`, an invented standard, saved as `can20.pdf`; no Bosch text is used anywhere.
The terms variable is set only with `monkeypatch`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from pdffixture import standard

from primarysource import cli, registry, terms
from primarysource.can import CAN, SPEC, name_file
from primarysource.errors import LibError
from primarysource.localpdf import library, store
from primarysource.localpdf.store import read_record

pytest.importorskip("pypdf")

PDF, IDS = standard()
VAR = "PRIMARYSOURCE_CAN_ACCEPT_TERMS"


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)
    monkeypatch.delenv(VAR, raising=False)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(VAR, "1")
    home = tmp_path / "can"
    home.mkdir()
    (home / "can20.pdf").write_bytes(PDF)
    store.import_folder(SPEC, home)
    return home


def test_the_file_name_the_pdf_circulates_under_is_the_bosch_document() -> None:
    for name in ("can20.pdf", "CAN2.0.pdf", "can_2.0 spec.pdf"):
        found = name_file(name, "")
        assert found is not None and found.doc == "bosch-2.0", name
    assert name_file("can_fd_spec.pdf", "") is None  # CAN FD is a different document, with no such grant
    assert name_file("can20.txt", "") is None


def test_import_is_refused_without_the_variable_and_the_error_names_no_url(tmp_path: Path) -> None:
    (tmp_path / "can20.pdf").write_bytes(PDF)
    with pytest.raises(LibError, match=VAR) as raised:
        store.import_folder(SPEC, tmp_path)
    assert "Robert Bosch GmbH" in raised.value.as_text() and "http" not in raised.value.as_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["can20.pdf"]


def test_the_import_cuts_at_bookmarks_into_sentences_and_records_the_acknowledgement(home: Path) -> None:
    entry = read_record(home)["documents"]["bosch-2.0"]
    assert entry["segmenter"] == "bookmarks" and entry["sections"] == len(IDS)
    assert list(read_record(home)[terms.RECORD_KEY]["documents"]) == ["bosch-2.0"]
    text = library.read(SPEC, "can:bosch-2.0§2", home=home)
    assert text.startswith("A gasket is a seal.\nA sprocket is a toothed wheel.\n§2.1 Gasket\n")
    assert "cite: Bosch CAN Specification 2.0, CAN Specification 2.0, §2 Terms" in text and "unit: sentence" in text


def test_a_sentence_ref_and_a_search_hit_name_the_document(home: Path) -> None:
    assert library.read(SPEC, "bosch-2.0§2¶2", home=home).startswith("A sprocket is a toothed wheel.")
    assert library.search(SPEC, "gasket round", home=home).splitlines()[0].startswith("can:bosch-2.0§2.1  Gasket:")
    assert "can:bosch-2.0§A" in library.outline(SPEC, "bosch-2.0", home=home)


def test_serving_is_refused_without_the_variable_or_without_a_record(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(VAR)
    with pytest.raises(LibError, match=VAR):
        library.read(SPEC, "bosch-2.0§2", home=home)
    monkeypatch.setenv(VAR, "true")
    assert library.read(SPEC, "bosch-2.0§2", home=home)
    (home / "install.json").write_text('{"documents": {}}', encoding="utf-8")
    with pytest.raises(LibError, match="no Bosch CAN specification documents are imported"):
        library.search(SPEC, "gasket", home=home)


def test_the_collection_is_registered_and_its_server_has_five_tools(home: Path) -> None:
    assert "can" in registry.available() and registry.load("can") is CAN
    assert CAN.grammar.parse("can:bosch-2.0§3.1¶2").para == 2
    pytest.importorskip("mcp")
    from primarysource.can.server import server

    assert [t.name for t in asyncio.run(server.list_tools())] == [
        "can_read",
        "can_search",
        "can_outline",
        "can_cite",
        "can_docs",
    ]


def test_the_command_refuses_then_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_CAN_HOME", str(tmp_path / "x"))
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "can20.pdf").write_bytes(PDF)
    assert cli.main(["can", "import"]) == 1
    assert VAR in capsys.readouterr().err
    monkeypatch.setenv(VAR, "1")
    assert cli.main(["can", "import"]) == 0
    assert "imported can:bosch-2.0" in capsys.readouterr().out
    assert cli.main(["can", "read", "bosch-2.0§2.1¶1"]) == 0
    assert capsys.readouterr().out.startswith("A gasket MUST be round.")


def test_the_cover_of_the_specification_is_recognised_and_can_fd_is_not() -> None:
    from primarysource import identify
    from primarysource.can.identify import identify as hook

    cover = identify.Probe("scan0001.pdf", "", ("BOSCH\n \nCAN Specification\n \nVersion 2.0\n \n1991\n",))
    (found,) = hook(cover)
    assert (found.designation, found.score) == ("Bosch CAN Specification 2.0", 3)
    assert found.command == 'primarysource can import "scan0001.pdf"'
    fd = identify.Probe("can_fd_spec.pdf", "", ("CAN with Flexible Data-Rate\n \nSpecification Version 1.0\n",))
    assert hook(fd) == []
    assert "can" in {name for name, _ in identify.registered_hooks()}


def test_front_matter_is_an_opt_in_section_before_the_first_bookmark() -> None:
    from primarysource.readers.bookmarks import cut

    pages = ["Invented cover. A notice sentence.", "1 Scope", "Body text here."]
    outline = [("1 Scope", 1, 0)]
    plain, _ = cut(pages, outline)
    kept, _ = cut(pages, outline, front_matter=True)
    assert [s["id"] for s in plain] == ["1"]
    assert [s["id"] for s in kept] == ["front-matter", "1"]
    assert "notice" in kept[0]["text"] and kept[0]["page"] == 1
