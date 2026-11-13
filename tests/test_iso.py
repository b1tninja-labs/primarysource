"""iso: designations, the folder importer, refs, the core index and the tools, over invented bookmarked PDFs.

No ISO text is used anywhere: the PDFs are `pdffixture.standard()`, an invented standard, saved under ISO-store
style file names.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from cursor_check import follow_list, follow_read
from pdffixture import standard

from primarysource import cli, registry
from primarysource.errors import LibError
from primarysource.iso import ISO, library
from primarysource.iso.designation import from_filename, parse
from primarysource.iso.importer import (
    EXTRACTED,
    INDEX_FILE,
    PURCHASED,
    import_file,
    import_folder,
    read_record,
)

pytest.importorskip("pypdf")

PDF, IDS = standard()
STORE_NAME = "ISO_IEC_9999_2024(en).pdf"


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


def _drop(home: Path, name: str = STORE_NAME, data: bytes = PDF) -> Path:
    folder = home / PURCHASED
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "iso"
    _drop(home)
    import_folder(home)
    return home


# --- designations ----------------------------------------------------------------------------------------------


def test_printed_designations_parse_to_label_doc_and_key() -> None:
    cases = {
        "ISO/IEC 9899:2024": ("ISO/IEC 9899:2024", "9899@2024", "9899_2024"),
        "ISO 8601-1:2019": ("ISO 8601-1:2019", "8601-1@2019", "8601-1_2019"),
        "ISO/IEC TR 24772-1:2019": ("ISO/IEC TR 24772-1:2019", "24772-1@2019", "24772-1_2019"),
        "ISO/IEC/IEEE 9945:2009": ("ISO/IEC/IEEE 9945:2009", "9945@2009", "9945_2009"),
        "ISO/IEC 27001:2022/Amd 1:2024": (
            "ISO/IEC 27001:2022/Amd 1:2024",
            "27001@2022+amd1-2024",
            "27001_2022_amd1-2024",
        ),
    }
    for text, (label, doc, key) in cases.items():
        found = parse(text)
        assert (found.label, found.doc, found.key) == (label, doc, key)


def test_store_file_names_carry_the_designation_and_others_do_not() -> None:
    found = from_filename("ISO_IEC_9899_2024(en).pdf")
    assert found is not None and found.label == "ISO/IEC 9899:2024"
    found = from_filename("ISO 8601-1 2019.pdf")
    assert found is not None and found.doc == "8601-1@2019"
    assert from_filename("notes.pdf") is None
    with pytest.raises(LibError, match="not an ISO designation") as raised:
        parse("C99")
    assert "as printed on the cover" in raised.value.hint


# --- the importer ----------------------------------------------------------------------------------------------


def test_the_folder_import_stores_an_extraction_a_record_and_an_index_but_no_copy_of_the_pdf(home: Path) -> None:
    entry = read_record(home)["documents"]["9999@2024"]
    assert entry["designation"] == "ISO/IEC 9999:2024"
    assert entry["source"] == str(home / PURCHASED / STORE_NAME)
    assert entry["size"] == len(PDF) and len(entry["sha256"]) == 64
    stored = json.loads((home / EXTRACTED / "9999_2024.json").read_text(encoding="utf-8"))
    assert [s["id"] for s in stored["sections"]] == IDS
    assert (home / INDEX_FILE).is_file()
    copies = [p for p in home.rglob("*") if p.is_file() and p.read_bytes() == PDF]
    assert copies == [home / PURCHASED / STORE_NAME]


def test_a_second_folder_import_skips_unchanged_files_and_names_what_it_cannot_import(home: Path) -> None:
    _drop(home, "notes.pdf")
    _drop(home, "ISO_1234_2020.pdf", b"not a pdf")
    done, skipped = import_folder(home)
    assert done == []
    reasons = dict(skipped)
    assert reasons[STORE_NAME] == "already imported, unchanged"
    assert "no designation in the file name" in reasons["notes.pdf"]
    assert "is not a PDF" in reasons["ISO_1234_2020.pdf"]


def test_one_file_imports_with_the_designation_printed_on_its_cover(tmp_path: Path) -> None:
    mine = tmp_path / "my copy.pdf"
    mine.write_bytes(PDF)
    with pytest.raises(LibError, match="no ISO designation in the file name") as raised:
        import_file(tmp_path / "iso", mine)
    assert "--designation" in raised.value.action
    result = import_file(tmp_path / "iso", mine, "ISO 8601-1:2019")
    assert (result.doc, result.designation, result.sections) == ("8601-1@2019", "ISO 8601-1:2019", len(IDS))


def test_a_missing_folder_is_an_error_naming_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="does not exist") as raised:
        import_folder(tmp_path / "iso")
    assert "put your ISO PDFs in it" in raised.value.action


# --- refs and reading ------------------------------------------------------------------------------------------


def test_refs_accept_the_prefix_a_printed_designation_and_a_bare_number() -> None:
    assert ISO.grammar.parse("iso:9999@2024§2.1¶1").doc == "9999@2024"
    ref = library.parse_ref("ISO/IEC 9999:2024§2.1¶1")
    assert (ref.doc, ref.section, ref.para) == ("9999@2024", "2.1", 1)
    assert library.parse_ref("9999§A").doc == "9999"
    assert library.parse_ref("iso:9999¶3").para == 3
    for bad in ("iso:9999:1-5", "§2.1", "iso:abc"):
        with pytest.raises(LibError):
            library.parse_ref(bad)


def test_read_a_clause_a_sentence_and_the_whole_standard(home: Path) -> None:
    text = library.read("iso:9999@2024§2", home=home)
    assert text.startswith(
        "A gasket is a seal.\nA sprocket is a toothed wheel.\n§2.1 Gasket\nA gasket MUST be round.\n§2.2 Sprocket\n"
    )
    assert "cite: ISO/IEC 9999:2024, Invented standard, §2 Terms" in text
    assert "unit: sentence" in text and "span: sha256:" in text
    assert library.read("ISO/IEC 9999:2024§2¶2", home=home).startswith("A sprocket is a toothed wheel.\n")
    assert library.read("9999§A", home=home).startswith("The registry lists flanges.")
    whole = library.read("9999", max_tokens=5000, home=home)
    assert whole.startswith("§1 Scope\n") and "§bibliography Bibliography\nRFC 9999 is invented." in whole


def test_a_read_cursor_is_a_ref_that_read_accepts_back(home: Path) -> None:
    for ref in ("9999§2", "iso:9999@2024", "9999§2¶2"):
        whole = library.read(ref, max_tokens=5000, home=home).rsplit("\n\ncite: ", 1)[0]
        bodies, refs = follow_read(lambda r: library.read(r, max_tokens=1, home=home), ref)
        assert len(refs) > 1 and "\n".join(bodies) == whole
    assert "next: iso:9999@2024§2¶2" in library.read("9999§2", max_tokens=1, home=home)


def test_cite_names_one_sentence_and_its_hash(home: Path) -> None:
    text = library.cite("9999§2.1¶1", home=home)
    assert text.startswith("iso:9999@2024§2.1¶1\n")
    assert "cite: ISO/IEC 9999:2024, Invented standard, §2.1 Gasket ¶1" in text and "span: sha256:" in text
    with pytest.raises(LibError, match="span has"):
        library.cite("9999§2.1¶9", home=home)


def test_a_bare_number_reads_the_newest_imported_year(home: Path) -> None:
    _drop(home, "ISO_IEC_9999_2026(en).pdf")
    import_folder(home)
    assert "iso:9999@2026" in library.outline("9999", home=home)
    assert "iso:9999@2024" in library.outline("9999@2024", home=home)


def test_outline_lists_every_clause_as_a_ref_and_pages(home: Path) -> None:
    text = library.outline("9999", home=home)
    for ident in IDS:
        assert f"iso:9999@2024§{ident}" in text
    rows = library.outline("9999", limit=100, home=home).rstrip("\n").split("\n")[1:]
    assert (
        follow_list(lambda start: "\n".join(library.outline("9999", start=start, limit=2, home=home).split("\n")[1:]))
        == rows
    )


# --- search through the core index -----------------------------------------------------------------------------


def test_search_finds_clauses_through_the_index_and_says_when_it_relaxed(home: Path) -> None:
    text = library.search("gasket round", home=home)
    assert text.splitlines()[0].startswith("iso:9999@2024§2.1  Gasket:")
    assert "relaxed:" not in text
    loose = library.search("flanges zeppelin", home=home)
    assert loose.splitlines()[0].startswith("iso:9999@2024§A") and "relaxed: only some query words matched" in loose
    assert library.search("zeppelin", home=home).startswith("no matches")


def test_search_reads_the_index_not_the_extraction(home: Path) -> None:
    (home / EXTRACTED / "9999_2024.json").unlink()
    assert library.search("gasket", home=home).startswith("iso:9999@2024§")


def test_search_pages_with_a_start_cursor_and_filters_by_document(home: Path) -> None:
    _drop(home, "ISO_IEC_9999_2026(en).pdf")
    import_folder(home)
    rows = library.search("a", limit=100, home=home).rstrip("\n").split("\n")
    assert follow_list(lambda start: library.search("a", limit=2, start=start, home=home)) == rows
    only = library.search("gasket", doc="9999@2026", limit=100, home=home)
    assert only.count("iso:9999@2026") >= 1 and "iso:9999@2024" not in only


def test_nothing_imported_and_a_missing_index_are_errors_with_an_action(home: Path, tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no ISO standards are imported") as raised:
        library.search("gasket", home=tmp_path / "empty")
    assert raised.value.action.endswith("primarysource iso import")
    (home / INDEX_FILE).unlink()
    with pytest.raises(LibError) as missing:
        library.search("gasket", home=home)
    assert missing.value.action == "primarysource iso index"
    with pytest.raises(LibError, match="ISO 1234 is not imported") as absent:
        library.read("1234§1", home=home)
    assert (
        absent.value.hint == "iso_docs lists what is imported" and "primarysource iso import" in absent.value.action
    )


def test_docs_says_when_a_source_pdf_changed_or_went_missing(home: Path) -> None:
    assert "(source unchanged)" in library.docs(home=home)
    (home / PURCHASED / STORE_NAME).write_bytes(PDF + b"\n")
    assert "(source changed since import)" in library.docs(home=home)
    (home / PURCHASED / STORE_NAME).unlink()
    assert "(source file missing)" in library.docs(home=home)
    assert library.read("9999§1", home=home).startswith("The widget protocol defines gaskets.")


# --- registration, CLI and MCP ---------------------------------------------------------------------------------


def test_the_collection_is_registered_with_its_extra() -> None:
    assert "iso" in registry.available()
    loaded = registry.load("iso")
    assert loaded is ISO and loaded.prefix == "iso_"


def test_the_command_imports_the_folder_and_reads_through_the_core_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    _drop(tmp_path / "iso")
    assert cli.main(["iso", "import"]) == 0
    assert "imported iso:9999@2024 (ISO/IEC 9999:2024)" in capsys.readouterr().out
    assert cli.main(["iso", "read", "9999§2.1¶1"]) == 0
    assert capsys.readouterr().out.startswith("A gasket MUST be round.")
    assert cli.main(["iso", "search", "gasket"]) == 0
    assert "iso:9999@2024§" in capsys.readouterr().out
    assert cli.main(["iso", "read", "9999§9.9"]) == 1
    assert "hint:" in capsys.readouterr().err


def test_the_server_serves_five_prefixed_text_tools(home: Path) -> None:
    pytest.importorskip("mcp")
    from primarysource.iso.server import server

    assert [t.name for t in asyncio.run(server.list_tools())] == [
        "iso_read",
        "iso_search",
        "iso_outline",
        "iso_cite",
        "iso_docs",
    ]
