"""identify: which collection knows a supplied PDF, and the iso importer's use of it.

Every document here is invented: the designations name standards that do not exist (ISO/IEC 9999, X.9999,
SP 800-999) or are only spelled, never quoted. The PDFs come from `pdffixture.make_pdf`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pdffixture import make_pdf

from primarysource import cli, identify
from primarysource.errors import LibError
from primarysource.identify import Probe
from primarysource.iso.importer import import_file, import_folder, read_record

pytest.importorskip("pypdf")

HEADER = "ISO/IEC 9999:2024(E)"
BODY = [
    ["1 Scope", "This document specifies widgets. It applies to gaskets."],
    ["2 Terms", "A widget is a part. A gasket is a seal.", "2.1 Widget", "A widget MUST be round."],
    ["2.2 Gasket", "A gasket SHOULD be soft. Its size is even.", "3 Conformance", "A product conforms if it works."],
    ["4 Testing", "Tests are run twice. Results are kept."],
]

CONTENTS = [
    ("1 Scope", 1),
    ("2 Terms", 2),
    ("2.1 Widget", 2),
    ("2.2 Gasket", 3),
    ("3 Conformance", 3),
    ("4 Testing", 4),
]


def iso_pdf(cover: tuple[str, ...] = ("Reference number", HEADER), bookmarks: bool = True) -> bytes:
    """An invented ISO-style PDF: a cover, then body pages that repeat the designation as a running header."""
    pages = [["INTERNATIONAL STANDARD", "ISO/IEC", "9999", "First edition", "2024-01-01", *cover]]
    contents = ["Contents Page"] + [f"{h} {'.' * 20} {n}" for h, n in CONTENTS]
    pages += [[HEADER, *contents, "© ISO/IEC 2024 - All rights reserved ii"]]
    pages += [[HEADER, *lines, f"© ISO/IEC 2024 - All rights reserved {n}"] for n, lines in enumerate(BODY, 1)]
    outline = (
        [("1 Scope", 2, 0), ("2 Terms", 3, 0), ("2.1 Widget", 3, 1), ("2.2 Gasket", 4, 1), ("3 Conformance", 4, 0)]
        + [("4 Testing", 5, 0)]
        if bookmarks
        else []
    )
    return make_pdf(pages, outline, title="Microsoft Word - C099999e.doc")


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


def _write(folder: Path, name: str, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return folder / name


# --- the common rule and each collection's hook ----------------------------------------------------------------


def test_the_cover_reference_number_and_running_header_outweigh_the_file_name() -> None:
    from primarysource.iso.identify import identify as iso

    probe = Probe(
        "ISO_9999_2024.pdf", "Microsoft Word - x.doc", ("Reference number\nISO/IEC 9999:2024(E)", HEADER, HEADER)
    )
    (best,) = iso(probe)
    assert best.designation == "ISO/IEC 9999:2024"
    assert best.evidence[0] == "cover reference number" and {"cover", "running header", "file name"} <= set(
        best.evidence
    )
    assert best.score == 3 + 3 + 2 + 1
    assert best.command == 'primarysource iso import "ISO_9999_2024.pdf" --designation "ISO/IEC 9999:2024"'


def test_a_file_name_alone_is_weak_and_one_later_page_counts_for_nothing() -> None:
    from primarysource.iso.identify import identify as iso

    (named,) = iso(Probe("ISO_IEC_9999_2024(en).pdf"))
    assert named.score == 1
    (once,) = iso(Probe("x.pdf", "", ("", "see ISO/IEC 9999:2024 for details")))
    assert once.score == 0 and once.evidence == ("one later page",)


def test_each_collection_recognises_its_own_designations() -> None:
    from primarysource.ecma.identify import identify as ecma
    from primarysource.ieee.identify import identify as ieee802
    from primarysource.itu.identify import identify as itu
    from primarysource.nist.identify import identify as nist

    assert itu(Probe("T-REC-X.9999-202401-I!!PDF-E.pdf", "", ("Recommendation ITU-T X.9999",)))[0].designation == (
        "Rec. ITU-T X.9999"
    )
    found = nist(Probe("x.pdf", "", ("NIST Special Publication 800-999 Revision 2", "NIST SP 800-999r2", "x")))
    assert {c.designation for c in found} == {"NIST SP 800-999 Rev. 2"}
    assert nist(Probe("x.pdf", "", ("FIPS PUB 999-1",)))[0].designation == "NIST FIPS 999-1"
    (std,) = ecma(Probe("ECMA-9999_1st_edition.pdf", "", ("Standard ECMA-9999",)))
    assert std.designation == "ECMA-9999" and std.command.startswith("primarysource ecma import 9999 --file")
    (dot,) = ieee802(Probe("x.pdf", "", ("IEEE Std 802.99Q-2024",)))
    assert dot.designation == "IEEE Std 802.99Q-2024" and "ieee802 import" in dot.command


def test_identify_ranks_across_collections_and_survives_a_failing_hook() -> None:
    from primarysource.itu.identify import identify as itu

    def broken(_probe: Probe) -> list[identify.Candidate]:
        raise LibError("broken", "")

    probe = Probe("x.pdf", "", ("Recommendation ITU-T X.9999", "Rec. ITU-T X.9999", "Rec. ITU-T X.9999"))
    found = identify.identify(probe, [("bad", broken), ("itu", itu)])
    assert [c.collection for c in found] == ["itu"] and found[0].score == 5


def test_the_command_reports_every_pdf_in_a_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, "scan 0042.pdf", iso_pdf())
    _write(tmp_path, "notes.pdf", make_pdf([["Nothing standard here."]], [("Notes", 0, 0)]))
    assert cli.main(["identify", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "scan 0042.pdf: ISO/IEC 9999:2024 (iso; cover reference number" in out
    assert '--designation "ISO/IEC 9999:2024"' in out
    assert "notes.pdf: not recognised as any collection's document" in out


# --- the iso importer uses it ----------------------------------------------------------------------------------


def test_a_renamed_download_imports_by_its_cover(tmp_path: Path) -> None:
    home = tmp_path / "iso"
    _write(home, "scan 0042.pdf", iso_pdf())
    done, skipped = import_folder(home)
    assert skipped == [] and [(r.doc, r.designation) for r in done] == [("9999@2024", "ISO/IEC 9999:2024")]


def test_a_file_named_for_another_standard_is_imported_as_what_its_cover_says(tmp_path: Path) -> None:
    result = import_file(tmp_path / "iso", _write(tmp_path, "ISO_1111_2020.pdf", iso_pdf()))
    assert result.doc == "9999@2024"
    assert result.note == "the file name says ISO 1111:2020, the PDF says ISO/IEC 9999:2024; using the PDF"


def test_another_collections_document_is_refused_with_its_command(tmp_path: Path) -> None:
    itu = make_pdf([["Recommendation ITU-T X.9999"], ["Rec. ITU-T X.9999", "1 Scope"]], [("1 Scope", 1, 0)])
    home = tmp_path / "iso"
    _write(home, "download.pdf", itu)
    done, skipped = import_folder(home)
    assert done == []
    ((name, reason),) = skipped
    assert name == "download.pdf" and "is Rec. ITU-T X.9999, a itu document, not an ISO standard" in reason
    assert "primarysource itu fetch X.9999" in reason


def test_a_pdf_without_bookmarks_is_cut_at_its_numbered_headings(tmp_path: Path) -> None:
    result = import_file(tmp_path / "iso", _write(tmp_path, "ISO_IEC_9999_2024.pdf", iso_pdf(bookmarks=False)))
    assert result.segmenter == "numbered headings" and result.headings_found == 6
    from primarysource.iso import library

    home = tmp_path / "iso"
    assert library.read("9999§2.1", home=home).startswith("A widget MUST be round.")
    assert "iso:9999@2024§front-matter" in library.outline("9999", home=home)
    assert read_record(home)["documents"]["9999@2024"]["segmenter"] == "numbered headings"
    assert HEADER not in library.read("9999", max_tokens=5000, home=home).split("\n\ncite: ")[0]


def test_numbered_cutting_is_only_for_callers_that_ask(tmp_path: Path) -> None:
    from primarysource.readers import pdf

    data = iso_pdf(bookmarks=False)
    with pytest.raises(LibError, match="no bookmarks"):
        pdf.extract(data)
    assert pdf.extract(data, numbered=True)["segmenter"] == "numbered headings"
    with pytest.raises(LibError, match="fewer than 3 numbered headings"):
        pdf.extract(make_pdf([["No headings."], ["Still none."]], []), numbered=True)


def test_a_useless_title_is_replaced_by_the_english_title_on_the_cover(tmp_path: Path) -> None:
    from primarysource.iso.identify import cover_title, useful_title

    probe = Probe(
        "x.pdf",
        "",
        (
            "INTERNATIONAL STANDARD\nISO/IEC 9999\nFirst edition 2024-01-01\nWidgets —\nPart 1: Gaskets\n"
            "Pièces — Partie 1: Joints\nReference number\nISO/IEC 9999-1:2024(E)",
        ),
    )
    assert cover_title(probe) == "Widgets — Part 1: Gaskets"
    assert not useful_title("Microsoft Word - C099999e.doc", "ISO/IEC 9999:2024")
    assert not useful_title("ISO/IEC 9999:2024", "ISO/IEC 9999:2024") and useful_title("Widgets", "ISO/IEC 9999:2024")
    result = import_file(tmp_path / "iso", _write(tmp_path, "ISO_IEC_9999_2024.pdf", iso_pdf()))
    assert read_record(tmp_path / "iso")["documents"][result.doc]["title"] == ""  # no title on that cover


def test_a_distributors_tracking_string_before_a_heading_is_removed() -> None:
    from primarysource.readers.bookmarks import clean_pages

    pages = ["--`,``,``,,,`,```,`,`,,`---1 Scope\nText.", "Other."]
    assert clean_pages(pages)[0][0] == "1 Scope"
    assert clean_pages(pages, keep_spacing=True)[0][0] == "1 Scope"
