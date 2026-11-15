"""gm: file naming, the page-per-section cut of table PDFs, the gated import, serving and the gate itself.

Invented tables only (`pdffixture.table_book`), saved under GM's file names. The terms variable is set only with
`monkeypatch`, on invented data; it is the owner's assertion and no test sets it for real files.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from cursor_check import follow_list, follow_read
from pdffixture import make_table_pdf, table_book

from primarysource import cli, registry, terms
from primarysource.errors import LibError
from primarysource.gm import GM, SPEC, name_file
from primarysource.localpdf import library, store
from primarysource.localpdf.store import EXTRACTED, INDEX_FILE, read_record
from primarysource.readers import bookmarks, pdf

pytest.importorskip("pypdf")

BOOK = table_book()
OTHER = make_table_pdf([[("P0100", "Other valve", "1 volt")]])
ENGINE = "17OBDG03 Engine Diagnostics.pdf"
TRANS = "17OBDG03 Transmisson Diagnostics.pdf"  # sic: GM's own spelling
VAR = "PRIMARYSOURCE_GM_ACCEPT_TERMS"


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)
    monkeypatch.delenv(VAR, raising=False)


@pytest.fixture
def accept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(VAR, "1")


def _drop(home: Path, name: str = ENGINE, data: bytes = BOOK) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / name
    path.write_bytes(data)
    return path


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(VAR, "1")
    home = tmp_path / "gm"
    _drop(home)
    store.import_folder(SPEC, home)
    return home


# --- naming ----------------------------------------------------------------------------------------------------


def test_gm_file_names_map_to_document_ids_and_gms_misspelling_is_corrected() -> None:
    cases = {
        "17OBDG01 Hybrid Diagnostics.pdf": "17OBDG01-hybrid",
        "17OBDG03 Engine Diagnostics.pdf": "17OBDG03-engine",
        "17OBDG03 Transmisson Diagnostics.pdf": "17OBDG03-transmission",
        "17OBDG03 Transmisson Diagnostics (1).pdf": "17OBDG03-transmission",
        "17OBDG05 Transmission Diagnostics.pdf": "17OBDG05-transmission",
        "2017_OBD_GROUP_SUMMARY.pdf": "2017-group-summary",
        "GM CAN mode $06 data final_dm.pdf": "mode6-can",
        "GM Class2 mode $06 data final_dm.pdf": "mode6-class2",
    }
    for name, doc in cases.items():
        found = name_file(name, "")
        assert found is not None and found.doc == doc and found.key == doc, name
    assert name_file("notes.pdf", "") is None


# --- cutting a table PDF ---------------------------------------------------------------------------------------


def test_a_table_pdf_is_cut_one_section_per_page_with_rows_on_one_line_and_furniture_dropped() -> None:
    out = pdf.extract(BOOK, None, pages_per_section=1)
    assert out["segmenter"] == "pages" and out["headings_found"] == 0 and out["pages"] == 5
    assert [s["id"] for s in out["sections"]] == ["p1", "p2", "p3", "p5"]
    assert out["sections"][0]["text"] == "P0010 | Valve circuit open | 5 volts\nP0011 | Valve performance | 250 ms"
    everything = "\n".join(s["text"] for s in out["sections"])
    assert "Description" not in everything and "Page 1 of 5" not in everything  # header row and footer


def test_a_page_without_a_text_layer_is_counted_not_a_failure() -> None:
    out = pdf.extract(BOOK, None, pages_per_section=1)
    assert out["empty_pages"] == 1 and "p4" not in [s["id"] for s in out["sections"]]


def test_pages_can_be_grouped_and_a_title_hook_names_a_section() -> None:
    out = pdf.extract(BOOK, None, pages_per_section=2, page_title=lambda a, b, lines: f"pages {a}-{b}")
    assert [(s["id"], s["title"], s["page"]) for s in out["sections"]] == [
        ("p1-2", "pages 1-2", 1),
        ("p3-4", "pages 3-4", 3),
        ("p5", "pages 5-5", 5),
    ]
    assert out["segmenter"] == "2 pages"
    with pytest.raises(ValueError, match="at least 1"):
        bookmarks.cut_pages(["x"], 0)


def test_a_long_first_line_is_cut_for_the_default_title() -> None:
    sections, _ = bookmarks.cut_pages(["word " * 40, "other\n"], 1)
    assert sections[0]["title"].endswith("...") and len(sections[0]["title"]) == bookmarks.TITLE_WIDTH


def test_the_page_bound_is_the_readers_and_a_pdf_over_it_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "MAX_PAGES", 3)
    with pytest.raises(LibError, match="5 pages, over the 3 bound"):
        pdf.extract(BOOK, None, pages_per_section=1)


# --- the gate on import ----------------------------------------------------------------------------------------


def test_import_is_refused_without_the_variable_and_touches_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "gm"
    _drop(folder)
    before = sorted(p.name for p in folder.iterdir())
    with pytest.raises(LibError, match=VAR) as raised:
        store.import_folder(SPEC, folder)
    assert str(folder) in raised.value.as_text() and "http" not in raised.value.as_text()
    with pytest.raises(LibError, match=VAR):
        store.import_file(SPEC, folder, folder / ENGINE)
    assert sorted(p.name for p in folder.iterdir()) == before  # no extraction, record or index


def test_a_refused_command_creates_no_home_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    where = tmp_path / "never-made"
    monkeypatch.setenv("PRIMARYSOURCE_GM_HOME", str(where))
    for argv in (["gm", "import"], ["gm", "index"], ["gm", "docs"], ["gm", "search", "valve"]):
        assert cli.main(argv) == 1
    assert not where.exists()


def test_the_import_records_the_acknowledgement_with_a_utc_time_and_the_document(home: Path) -> None:
    record = read_record(home)
    block = record[terms.RECORD_KEY]
    assert block["variable"] == VAR and list(block["documents"]) == ["17OBDG03-engine"]
    assert block["documents"]["17OBDG03-engine"].endswith("+00:00")


def test_a_later_import_merges_and_keeps_the_first_timestamp(home: Path) -> None:
    first = terms.recorded(read_record(home))
    _drop(home, "17OBDG01 Hybrid Diagnostics.pdf", OTHER)
    store.import_folder(SPEC, home)
    now = terms.recorded(read_record(home))
    assert sorted(now) == ["17OBDG01-hybrid", "17OBDG03-engine"]
    assert now["17OBDG03-engine"] == first["17OBDG03-engine"]


def test_an_unrecognised_variable_value_is_an_error_not_a_refusal_to_guess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(VAR, "perhaps")
    with pytest.raises(LibError, match="is not a yes or a no"):
        store.import_folder(SPEC, tmp_path)


# --- the importer ----------------------------------------------------------------------------------------------


def test_the_import_stores_an_extraction_a_record_and_an_index_but_no_copy_of_the_pdf(home: Path) -> None:
    entry = read_record(home)["documents"]["17OBDG03-engine"]
    assert entry["label"] == "GM 17OBDG03 Engine Diagnostics" and entry["segmenter"] == "pages"
    assert entry["size"] == len(BOOK) and len(entry["sha256"]) == 64 and entry["pages"] == 5
    stored = json.loads((home / EXTRACTED / "17OBDG03-engine.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in stored["sections"]] == ["p1", "p2", "p3", "p5"]
    assert (home / INDEX_FILE).is_file()
    assert [p for p in home.rglob("*") if p.is_file() and p.read_bytes() == BOOK] == [home / ENGINE]


def test_two_files_with_the_same_bytes_import_once_and_the_copy_is_noted(tmp_path: Path, accept: None) -> None:
    folder = tmp_path / "gm"
    _drop(folder, TRANS)
    _drop(folder, "17OBDG03 Transmisson Diagnostics (1).pdf")
    done, skipped = store.import_folder(SPEC, folder)
    assert [r.doc for r in done] == ["17OBDG03-transmission"]
    assert skipped == [("17OBDG03 Transmisson Diagnostics (1).pdf", "skipped duplicate of gm:17OBDG03-transmission")]
    assert read_record(folder)["documents"]["17OBDG03-transmission"]["source"] == str(folder / TRANS)
    # and again: the original is unchanged, the copy is still a duplicate, nothing is imported twice
    done, skipped = store.import_folder(SPEC, folder)
    assert done == [] and dict(skipped)["17OBDG03 Transmisson Diagnostics (1).pdf"].startswith("skipped duplicate of")


def test_the_copy_is_the_one_skipped_even_when_it_sorts_first(tmp_path: Path, accept: None) -> None:
    folder = tmp_path / "gm"
    _drop(folder, "17OBDG03 Transmisson Diagnostics (1).pdf")
    _drop(folder, TRANS)
    store.import_folder(SPEC, folder)
    assert read_record(folder)["documents"]["17OBDG03-transmission"]["source"] == str(folder / TRANS)


def test_a_second_file_for_the_same_document_with_other_bytes_is_not_silently_taken(
    tmp_path: Path, accept: None
) -> None:
    folder = tmp_path / "gm"
    _drop(folder, TRANS)
    _drop(folder, "17OBDG03 Transmisson Diagnostics (1).pdf", make_table_pdf([[("P0999", "Other", "1")]]))
    _, skipped = store.import_folder(SPEC, folder)
    assert (
        "already taken by another file with other bytes" in dict(skipped)["17OBDG03 Transmisson Diagnostics (1).pdf"]
    )


def test_unknown_names_and_non_pdfs_are_skipped_with_a_reason(home: Path) -> None:
    _drop(home, "notes.pdf")
    _drop(home, "17OBDG09 Engine Diagnostics.pdf", b"not a pdf")
    done, skipped = store.import_folder(SPEC, home)
    reasons = dict(skipped)
    assert done == [] and reasons[ENGINE] == "already imported, unchanged"
    assert "not a file name the gm collection knows" in reasons["notes.pdf"]
    assert "is not a PDF" in reasons["17OBDG09 Engine Diagnostics.pdf"]


def test_a_missing_folder_names_the_variable_that_moves_it(tmp_path: Path, accept: None) -> None:
    with pytest.raises(LibError, match="does not exist") as raised:
        store.import_folder(SPEC, tmp_path / "gm")
    assert "PRIMARYSOURCE_GM_HOME" in raised.value.hint


# --- reading ---------------------------------------------------------------------------------------------------


def test_a_search_hit_is_a_page_ref_titled_by_its_fault_codes(home: Path) -> None:
    text = library.search(SPEC, "valve", home=home)
    assert text.splitlines()[0].startswith("gm:17OBDG03-engine§p1  P0010, P0011:")
    assert library.search(SPEC, "P0012", home=home).startswith("gm:17OBDG03-engine§p2  P0012:")
    assert library.search(SPEC, "zeppelin", home=home).startswith("no matches")


def test_a_page_with_no_fault_code_is_titled_by_its_first_line(home: Path) -> None:
    assert "gm:17OBDG03-engine§p3  Supporting table | Gasket pressure | 40 kPa:" in library.search(
        SPEC, "gasket", home=home
    )


def test_read_a_page_a_line_and_the_whole_document_with_the_block_unit(home: Path) -> None:
    text = library.read(SPEC, "gm:17OBDG03-engine§p1", home=home)
    assert text.startswith("P0010 | Valve circuit open | 5 volts\nP0011 | Valve performance | 250 ms\n")
    assert "cite: GM 17OBDG03 Engine Diagnostics, 2017 OBD parameter file, §p1 P0010, P0011" in text
    assert "unit: block" in text and "span: sha256:" in text
    assert library.read(SPEC, "17OBDG03-engine§p1¶2", home=home).startswith("P0011 | Valve performance | 250 ms")
    whole = library.read(SPEC, "17OBDG03-engine", max_tokens=5000, home=home)
    assert whole.startswith("§p1 P0010, P0011\nP0010 |") and "§p5 Notes | Invented note | none" in whole


def test_a_document_id_is_found_ignoring_case(home: Path) -> None:
    assert library.read(SPEC, "17obdg03-ENGINE§p2", home=home).startswith("P0012 |")


def test_a_read_cursor_is_a_ref_that_read_accepts_back(home: Path) -> None:
    for ref in ("17OBDG03-engine§p1", "gm:17OBDG03-engine"):
        whole = library.read(SPEC, ref, max_tokens=5000, home=home).rsplit("\n\ncite: ", 1)[0]
        bodies, refs = follow_read(lambda r: library.read(SPEC, r, max_tokens=1, home=home), ref)
        assert len(refs) > 1 and "\n".join(bodies) == whole


def test_cite_names_one_line_and_its_hash(home: Path) -> None:
    text = library.cite(SPEC, "17OBDG03-engine§p1¶1", home=home)
    assert text.startswith("gm:17OBDG03-engine§p1¶1\n") and "span: sha256:" in text and "unit: block" in text
    with pytest.raises(LibError, match="span has 2 blocks"):
        library.cite(SPEC, "17OBDG03-engine§p1¶9", home=home)


def test_outline_lists_pages_as_refs_and_pages_through_a_cursor(home: Path) -> None:
    text = library.outline(SPEC, "17OBDG03-engine", home=home)
    assert "p3 Supporting table | Gasket pressure | 40 kPa  gm:17OBDG03-engine§p3  (p. 3)" in text
    rows = library.outline(SPEC, "17OBDG03-engine", limit=100, home=home).rstrip("\n").split("\n")[1:]
    paged = follow_list(
        lambda start: "\n".join(
            library.outline(SPEC, "17OBDG03-engine", start=start, limit=1, home=home).split("\n")[1:]
        )
    )
    assert paged == rows


def test_search_pages_with_a_start_cursor(home: Path) -> None:
    rows = library.search(SPEC, "a", limit=100, home=home).rstrip("\n").split("\n")
    assert follow_list(lambda start: library.search(SPEC, "a", limit=1, start=start, home=home)) == rows


def test_docs_says_when_a_source_changed_and_when_the_acknowledgement_was_recorded(home: Path) -> None:
    text = library.docs(SPEC, home=home)
    assert "(source unchanged; terms acknowledged 20" in text and "+00:00)" in text
    (home / ENGINE).write_bytes(BOOK + b"\n")
    assert "source changed since import" in library.docs(SPEC, home=home)


def test_bad_refs_are_errors_naming_the_form(home: Path) -> None:
    for bad in ("gm:§p1", "gm:17OBDG03-engine:1-5", "gm:17OBDG03-engine#x"):
        with pytest.raises(LibError):
            library.read(SPEC, bad, home=home)
    with pytest.raises(LibError, match="not imported") as raised:
        library.read(SPEC, "17OBDG99-engine§p1", home=home)
    assert raised.value.hint == "gm_docs lists what is imported" and "primarysource gm import" in raised.value.action


# --- the gate on serving ---------------------------------------------------------------------------------------


def test_every_read_is_refused_when_the_variable_is_withdrawn(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VAR)
    calls = (
        lambda: library.read(SPEC, "17OBDG03-engine§p1", home=home),
        lambda: library.outline(SPEC, "17OBDG03-engine", home=home),
        lambda: library.search(SPEC, "valve", home=home),
        lambda: library.cite(SPEC, "17OBDG03-engine§p1", home=home),
        lambda: library.docs(SPEC, home=home),
        lambda: store.rebuild_index(SPEC, home),
    )
    for call in calls:
        with pytest.raises(LibError, match=VAR) as raised:
            call()
        assert str(home) in raised.value.as_text()


def test_an_index_built_outside_the_gate_is_refused_even_with_the_variable_set(home: Path) -> None:
    record = read_record(home)
    del record[terms.RECORD_KEY]
    (home / "install.json").write_text(json.dumps(record), encoding="utf-8")
    for call in (
        lambda: library.read(SPEC, "17OBDG03-engine§p1", home=home),
        lambda: library.search(SPEC, "valve", home=home),
        lambda: library.docs(SPEC, home=home),
        lambda: store.rebuild_index(SPEC, home),
    ):
        with pytest.raises(LibError, match="no terms acknowledgement is recorded for 17OBDG03-engine") as raised:
            call()
        assert raised.value.action == "primarysource gm import"


def test_a_document_without_a_record_blocks_the_search_of_the_others(home: Path) -> None:
    _drop(home, "17OBDG01 Hybrid Diagnostics.pdf", OTHER)
    store.import_folder(SPEC, home)
    record = read_record(home)
    del record[terms.RECORD_KEY]["documents"]["17OBDG01-hybrid"]
    (home / "install.json").write_text(json.dumps(record), encoding="utf-8")
    assert library.read(SPEC, "17OBDG03-engine§p1", home=home).startswith("P0010")
    with pytest.raises(LibError, match="17OBDG01-hybrid"):
        library.read(SPEC, "17OBDG01-hybrid§p1", home=home)
    with pytest.raises(LibError, match="17OBDG01-hybrid"):
        library.search(SPEC, "valve", home=home)


def test_nothing_imported_and_a_missing_index_are_errors_with_an_action(home: Path, tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no GM OBD parameter files documents are imported") as raised:
        library.search(SPEC, "valve", home=tmp_path / "empty")
    assert raised.value.action.endswith("primarysource gm import")
    (home / INDEX_FILE).unlink()
    with pytest.raises(LibError) as missing:
        library.search(SPEC, "valve", home=home)
    assert missing.value.action == "primarysource gm index"


# --- registration, CLI and MCP ---------------------------------------------------------------------------------


def test_the_collection_is_registered_behind_its_own_extra() -> None:
    assert "gm" in registry.available()
    loaded = registry.load("gm")
    assert loaded is GM and loaded.prefix == "gm_"
    assert loaded.grammar.parse("gm:17OBDG01-hybrid§p12¶3").section == "p12"


def test_the_command_imports_and_reads_through_the_core_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_GM_HOME", str(tmp_path / "elsewhere"))
    _drop(tmp_path / "elsewhere")
    assert cli.main(["gm", "import"]) == 1
    assert VAR in capsys.readouterr().err
    monkeypatch.setenv(VAR, "yes")
    assert cli.main(["gm", "import"]) == 0
    out = capsys.readouterr().out
    assert "imported gm:17OBDG03-engine (GM 17OBDG03 Engine Diagnostics): 4 sections from 5 pages (pages)" in out
    assert "1 pages have no text layer" in out
    assert cli.main(["gm", "read", "17OBDG03-engine§p2¶1"]) == 0
    assert capsys.readouterr().out.startswith("P0012 | Pump circuit low | 2 volts")
    assert cli.main(["gm", "search", "pump"]) == 0
    assert "gm:17OBDG03-engine§p2" in capsys.readouterr().out
    assert cli.main(["gm", "read", "17OBDG03-engine§p9"]) == 1
    assert "hint:" in capsys.readouterr().err


def test_a_single_file_can_be_imported_by_path(tmp_path: Path, accept: None) -> None:
    mine = _drop(tmp_path / "somewhere", "17OBDG01 Hybrid Diagnostics.pdf")
    result = store.import_file(SPEC, tmp_path / "gm", mine)
    assert (result.doc, result.sections, result.empty_pages) == ("17OBDG01-hybrid", 4, 1)
    with pytest.raises(LibError, match="not a file name the gm collection knows"):
        store.import_file(SPEC, tmp_path / "gm", _drop(tmp_path / "somewhere", "random.pdf"))


def test_the_server_serves_five_prefixed_text_tools_that_refuse_without_the_variable(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from mcp.server.mcpserver.exceptions import ToolError

    from primarysource.gm.server import server

    assert [t.name for t in asyncio.run(server.list_tools())] == [
        "gm_read",
        "gm_search",
        "gm_outline",
        "gm_cite",
        "gm_docs",
    ]
    monkeypatch.setenv("PRIMARYSOURCE_GM_HOME", str(home))
    monkeypatch.delenv(VAR)
    with pytest.raises(ToolError, match=VAR):
        asyncio.run(server.call_tool("gm_docs", {}))
    monkeypatch.setenv(VAR, "1")
    result = asyncio.run(server.call_tool("gm_read", {"ref": "17OBDG03-engine§p2"}))
    assert "P0012 | Pump circuit low | 2 volts" in str(result)


def test_the_mode_06_files_are_recognised_by_the_data_link_their_first_page_names() -> None:
    from primarysource import identify
    from primarysource.gm.identify import identify as hook

    first = "GM mode $06 data definitions for GM vehicles using GMLAN diagnostic data link\n"
    can = identify.Probe("a.pdf", "", (first,))
    second = "Mode $06 data definitions for GM vehicles using J1850/Class2  diagnostic data link"
    class2 = identify.Probe("b.pdf", "", (second,))
    assert [c.designation for c in hook(can)] == ["GM Mode $06 CAN (GMLAN)"]
    assert [c.designation for c in hook(class2)] == ["GM Mode $06 Class2 (J1850)"]
    assert hook(can)[0].command == 'primarysource gm import "a.pdf"'
    assert hook(identify.Probe("c.pdf", "", ("Component/ System Fault Code",))) == []
    assert "gm" in {name for name, _ in identify.registered_hooks()}
