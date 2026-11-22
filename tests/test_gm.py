"""gm: file-name designations, the table segmenters, the importer and the shared tools, over invented text.

No GM text is used anywhere. The pages are invented tables with the shape of GM's (running title, a DTC column, a
Mode $06 id pair), and the PDFs are `pdffixture.make_pdf` pages saved under GM-style file names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pdffixture import make_pdf

from primarysource import cli, registry
from primarysource.errors import LibError
from primarysource.gm import COLLECTION, REF_PREFIX
from primarysource.gm.designation import designate
from primarysource.gm.importer import import_files, pdfs_in
from primarysource.gm.segment import page_title, segment
from primarysource.gm.spec import SPEC
from primarysource.pdfcorpus import corpus as pdfcorpus_corpus
from primarysource.pdfcorpus import tools

pytest.importorskip("pypdf")


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


# ---- designations ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "doc_id", "number"),
    [
        ("17OBDG01 Hybrid Diagnostics.pdf", "17OBDG01-hybrid", "GM 17OBDG01 Hybrid Diagnostics"),
        ("17OBDG03 Engine Diagnostics.pdf", "17OBDG03-engine", "GM 17OBDG03 Engine Diagnostics"),
        ("17OBDG03 Transmisson Diagnostics (1).pdf", "17OBDG03-transmission", "GM 17OBDG03 Transmission Diagnostics"),
        ("2017_OBD_GROUP_SUMMARY.pdf", "2017-group-summary", "GM 2017 OBD Group Summary"),
        ("GM CAN mode $06 data final_dm.pdf", "mode6-can", "GM Mode $06 data definitions (CAN)"),
        ("GM Class2 mode $06 data final_dm.pdf", "mode6-class2", "GM Mode $06 data definitions (Class2)"),
    ],
)
def test_a_file_name_gives_its_document_id_and_citation_name(name: str, doc_id: str, number: str) -> None:
    found = designate(name)
    assert (found.doc_id, found.number) == (doc_id, number)


def test_an_unknown_name_is_refused_with_the_remedy_and_id_overrides_it() -> None:
    with pytest.raises(LibError) as raised:
        designate("brochure.pdf")
    assert "--id" in raised.value.hint
    assert designate("brochure.pdf", "brochure").doc_id == "brochure"
    with pytest.raises(LibError, match="not a document id"):
        designate("brochure.pdf", "bad id!")


# ---- segmenters -----------------------------------------------------------------------------------------------


def _summary_page(title: str, rows: list[tuple[str, str]]) -> str:
    out = [f"                17 OBDG99 {title}", "", "Component   Fault Code  Description"]
    out += [f"{part:<12}{code}  invented description of {code}" for part, code in rows]
    out += ["", "                                   ECM Section 1 of 9      7"]
    return "\n".join(out)


def test_diagnostic_pages_become_a_run_per_title_and_a_child_per_dtc() -> None:
    pages = [
        _summary_page("ECM Summary Tables (Invented)", [("Widget", "P0123")]),
        "   17 OBDG99 ECM Summary Tables (Invented)\n\nfurther text of the same fault, a continuation page",
        _summary_page("ECM Summary Tables (Invented)", [("Gadget", "P0456"), ("Sprocket", "U0100")]),
        "   17 OBDG99\nInitial Supporting table - P0456_Threshold\nDescription: invented",
    ]
    cut = segment(pages, "diagnostics")
    ids = [s.id for s in cut.sections]
    assert ids == [
        "ecm-summary-tables-invented",
        "P0123",
        "P0456",
        "U0100",
        "initial-supporting-table-p0456-threshold",
    ]
    run, first = cut.sections[0], cut.sections[1]
    assert run.start_line == 1 and run.end_line > first.end_line
    assert cut.lines[first.start_line - 1].lstrip().startswith("Widget")
    # a DTC runs to the line before the next one
    assert first.end_line == cut.sections[2].start_line - 1
    assert cut.lines[0] == "[page 1]"


def test_a_dtc_that_repeats_in_one_document_gets_a_numbered_id() -> None:
    pages = [
        _summary_page("ECM Summary Tables (A)", [("One", "P0100")]),
        _summary_page("TCM Summary Tables", [("Two", "P0100")]),
    ]
    found = [s.id for s in segment(pages, "diagnostics").sections if s.id.startswith("P")]
    assert found == ["P0100", "P0100-2"]


def test_a_dtc_named_in_a_description_is_not_a_section() -> None:
    page = _summary_page("ECM Summary Tables", [("One", "P0100")]) + "\nsee P0200 for the related fault"
    assert [s.id for s in segment([page], "diagnostics").sections if s.id.startswith("P")] == ["P0100"]


def test_the_running_title_drops_the_group_prefix_and_the_page_number_column() -> None:
    assert (
        page_title("17 OBDG01 ECM Summary Tables (Initial DTCs)      12\nrest") == "ECM Summary Tables (Initial DTCs)"
    )
    assert page_title("17 OBDG01\nInitial Supporting table -X   \nmore") == "Initial Supporting table -X"
    assert page_title("   \n\n") == ""


MODE6_PAGES = [
    "\n".join(
        [
            "          Invented mode $06 data definitions",
            "",
            "                  Invented Sensor Monitor Bank 1",
            "",
            "01        01       0A      Invented threshold voltage            0 to 8 Volts",
            "01        02 (16)  0A      Invented switch time                  0 to 9 ms",
            "                                       a wrapped description line",
            "01        02       10      Invented second row for the same ids",
        ]
    ),
    "\n".join(["                  Invented Heater Monitor Bank 1", "02        04       10      Invented heater row"]),
    "\n".join(
        ["          Invented mode $06 data definitions", "(1) invented footnote text", "(2) another invented note"]
    ),
]


def test_mode6_pages_become_monitors_with_a_child_per_test_row_and_the_footnotes() -> None:
    cut = segment(MODE6_PAGES, "mode6")
    assert [s.id for s in cut.sections] == [
        "mon-invented-sensor-monitor-bank-1",
        "01-01",
        "01-02",
        "01-02-2",
        "mon-invented-heater-monitor-bank-1",
        "02-04",
        "footnotes",
    ]
    by = {s.id: s for s in cut.sections}
    assert by["01-02"].end_line == by["01-02-2"].start_line - 1
    assert (
        by["mon-invented-sensor-monitor-bank-1"].end_line == by["mon-invented-heater-monitor-bank-1"].start_line - 1
    )
    assert by["footnotes"].end_line == len(cut.lines)
    assert cut.kind == "mode6"


def test_a_file_with_no_recognised_tables_falls_back_to_a_section_per_page() -> None:
    cut = segment(["first page", "second page"], "mode6")
    assert [(s.id, s.heading) for s in cut.sections] == [("p1", "page 1"), ("p2", "page 2")]
    assert cut.kind == "pages"


# ---- importer, tools and wiring ------------------------------------------------------------------------------


def _summary_pdf() -> bytes:
    return make_pdf([["Invented matrix row alpha", "Invented matrix row beta"], ["Invented second page"]], [])


@pytest.fixture
def home(tmp_path: Path) -> Path:
    folder = tmp_path / "gm"
    folder.mkdir()
    (folder / "2017_OBD_GROUP_SUMMARY.pdf").write_bytes(_summary_pdf())
    return folder


def test_import_writes_text_index_and_search_and_the_tools_cite_with_the_prefix(home: Path, tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    report = import_files(SPEC, pdfs_in(home), root=root)
    assert [(r.status, r.doc_id, r.pages) for r in report.results] == [("imported", "2017-group-summary", 2)]
    assert report.indexed_sections == 2
    assert (root / "text" / "2017-group-summary.txt").is_file()
    record = json.loads((root / "install.json").read_text(encoding="utf-8"))["documents"]["2017-group-summary"]
    assert record["no_text_pages"] == [] and record["segmenter"] == "pages"
    loaded = pdfcorpus_corpus.load_corpus(SPEC, root)
    assert not (home / "corpus").exists()  # an explicit root is the only place anything is written
    assert "alpha" in tools.search(loaded, "alpha")
    read = tools.read(loaded, f"{REF_PREFIX}2017-group-summary§p1")
    assert "Invented matrix row beta" in read and "cite: GM 2017 OBD Group Summary §p1" in read
    assert tools.cite(loaded, "gm:2017-group-summary", "p2").startswith("GM 2017 OBD Group Summary §p2")
    assert "sha256: " in tools.info(loaded, "gm:2017-group-summary")


def test_an_unchanged_file_is_skipped_a_copy_is_named_and_an_unknown_name_is_reported(
    home: Path, tmp_path: Path
) -> None:
    root = tmp_path / "corpus"
    import_files(SPEC, pdfs_in(home), root=root)
    (home / "2017_OBD_GROUP_SUMMARY (1).pdf").write_bytes(_summary_pdf())
    (home / "brochure.pdf").write_bytes(make_pdf([["x"]], []))
    statuses = {r.file: r for r in import_files(SPEC, pdfs_in(home), root=root).results}
    assert statuses["2017_OBD_GROUP_SUMMARY.pdf"].status == "unchanged"
    assert statuses["2017_OBD_GROUP_SUMMARY (1).pdf"].status == "duplicate"
    assert statuses["brochure.pdf"].status == "skipped" and "--id" in statuses["brochure.pdf"].note
    forced = import_files(SPEC, [home / "2017_OBD_GROUP_SUMMARY.pdf"], root=root, force=True)
    assert forced.results[0].status == "imported"


def test_the_id_option_takes_one_file_only(home: Path, tmp_path: Path) -> None:
    with pytest.raises(LibError, match="exactly one file"):
        import_files(SPEC, pdfs_in(home) * 2, root=tmp_path / "c", doc_id="x")


def test_an_empty_or_missing_home_says_where_to_put_the_pdfs(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no PDFs"):
        pdfs_in(tmp_path)
    with pytest.raises(LibError, match="not a folder"):
        pdfs_in(tmp_path / "absent")


def test_a_corrupt_pdf_is_skipped_not_fatal(home: Path, tmp_path: Path) -> None:
    (home / "17OBDG01 Hybrid Diagnostics.pdf").write_bytes(b"not a pdf")
    results = {r.file: r.status for r in import_files(SPEC, pdfs_in(home), root=tmp_path / "c").results}
    assert results == {"17OBDG01 Hybrid Diagnostics.pdf": "skipped", "2017_OBD_GROUP_SUMMARY.pdf": "imported"}


def test_the_home_setting_and_the_command_line(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_GM_HOME", str(home))
    monkeypatch.delenv("PRIMARYSOURCE_GM_CORPUS", raising=False)
    assert cli.main(["gm", "import"]) == 0
    assert "imported   2017-group-summary: 2 pages, 2 sections (pages)" in capsys.readouterr().out
    assert (home / "corpus" / "index.json").is_file()  # the corpus lands beside the PDFs, in the home
    assert cli.main(["gm", "index"]) == 0
    assert cli.main(["gm"]) == 2


def test_the_collection_is_registered_and_serves_the_five_prefixed_tools() -> None:
    assert "gm" in registry.available()
    assert registry.load("gm") is COLLECTION
    served = {t.name for t in cli.build_server(["gm"])._tool_manager.list_tools()}
    assert served == {f"gm_{tool}" for tool in ("search", "read", "outline", "info", "cite")}


def test_a_missing_corpus_names_the_import_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_GM_CORPUS", str(tmp_path / "none"))
    with pytest.raises(LibError) as raised:
        pdfcorpus_corpus.load_corpus(SPEC)
    assert raised.value.action == "primarysource gm import"


def test_the_collection_ref_parser_accepts_the_prefix() -> None:
    parser = COLLECTION.grammar
    ref = parser.parse("gm:17OBDG01-hybrid§P0010")
    assert (ref.doc, ref.section) == ("17OBDG01-hybrid", "P0010")
    assert parser.parse("mode6-can:10-20").lines == (10, 20)
    assert parser.format(ref) == "gm:17OBDG01-hybrid§P0010"
