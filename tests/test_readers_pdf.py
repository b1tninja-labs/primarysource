"""The core PDF reader (`cl.reader_pdf_pypdf`) and bookmark segmenter (`cl.segment_bookmarks`), over an invented
bookmarked PDF. Moved from `tests/test_ecma.py` with the reader."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pdffixture import make_pdf, standard

from primarysource.errors import LibError
from primarysource.readers import bookmarks, pdf

pytest.importorskip("pypdf")

PDF, IDS = standard()


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


def test_bookmarks_become_numbered_sections_with_sentences() -> None:
    extracted = pdf.extract(PDF)
    assert [s["id"] for s in extracted["sections"]] == IDS
    assert extracted["pages"] == 5 and extracted["extractor"].startswith("pypdf") and extracted["headings_found"] == 7
    by_id = {s["id"]: s for s in extracted["sections"]}
    assert by_id["1"]["text"].split("\n") == [
        "The widget protocol defines gaskets.",
        "It applies to sprockets.",
        "This sentence is padding for the furniture filter.",
    ]
    assert (
        by_id["2.1"]["text"] == "A gasket MUST be round." and by_id["2.1"]["depth"] == 1 and by_id["2.1"]["page"] == 2
    )
    assert by_id["A"]["title"] == "(normative) Registry" and by_id["A"]["text"].startswith(
        "The registry lists flanges."
    )
    assert by_id["bibliography"]["text"].splitlines()[0] == "RFC 9999 is invented."


def test_page_furniture_is_dropped_but_ordinary_text_stays() -> None:
    text = " ".join(s["text"] for s in pdf.extract(PDF)["sections"])
    assert "INVENTED STANDARD" not in text and "Page 3 of 5" not in text and "Draft for tests only" not in text
    assert "A sprocket SHOULD have teeth." in text


def test_sentences_split_after_a_stop_before_a_capital_but_not_after_abbreviations() -> None:
    assert bookmarks.split_sentences(
        "One thing, e.g. a gasket. Two things! Is it three? Yes (see 4.2). 5 is next."
    ) == [
        "One thing, e.g. a gasket.",
        "Two things!",
        "Is it three?",
        "Yes (see 4.2).",
        "5 is next.",
    ]
    assert bookmarks.split_sentences("   ") == []


def test_heading_ids() -> None:
    assert bookmarks.heading_id("5.3 Separator characters") == ("5.3", "Separator characters")
    assert bookmarks.heading_id("A.2.1 Data Types") == ("A.2.1", "Data Types")
    assert bookmarks.heading_id("Annex A. RPC Methods") == ("A", "RPC Methods")
    assert bookmarks.heading_id("Appendix I. Guidelines") == ("Appendix-I", "Guidelines")
    assert bookmarks.heading_id("Bibliography") == ("bibliography", "Bibliography")


def test_a_pdf_with_no_bookmarks_junk_or_too_many_pages_is_refused() -> None:
    with pytest.raises(LibError, match="no bookmarks"):
        pdf.extract(make_pdf([["hello"]], []))
    with pytest.raises(LibError, match="could not read the PDF"):
        pdf.extract(b"%PDF-1.4\nthis is not a pdf at all")
    with pytest.raises(LibError, match="byte bound"):
        pdf.extract(b"x" * (pdf.MAX_BYTES + 1))
    with pytest.raises(LibError, match="could not read the PDF"):
        pdf.extract(b"")


def test_a_bookmark_that_never_matches_a_heading_still_yields_a_section() -> None:
    odd = make_pdf([["alpha beta gamma."], ["delta."]], [("7 Missing heading", 0, 0), ("8 Other", 1, 0)])
    sections = pdf.extract(odd)["sections"]
    assert [s["id"] for s in sections] == ["7", "8"]
    assert "alpha beta gamma." in sections[0]["text"] or "alpha beta gamma." in sections[1]["text"]


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is not installed")
def test_pdftotext_is_used_when_present_and_gives_the_same_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.undo()  # put the real shutil.which back
    path = tmp_path / "x.pdf"
    path.write_bytes(PDF)
    extracted = pdf.extract(PDF, path)
    backend = pdf.pdftotext_backend()
    assert backend is not None and backend.name == "pdftotext" and backend.version
    assert extracted["extractor"] == backend.label() and extracted["extractor"].startswith("pdftotext ")
    assert [s["id"] for s in extracted["sections"]] == IDS
    assert "A gasket MUST be round." in {s["id"]: s for s in extracted["sections"]}["2.1"]["text"]


def test_the_backend_name_and_version_are_exposed_for_an_index_to_hash() -> None:
    import pypdf

    backend = pdf.pypdf_backend()
    assert backend == pdf.Backend("pypdf", pypdf.__version__) and backend.label() == f"pypdf {pypdf.__version__}"
    extracted = pdf.extract(PDF)
    assert extracted["extractor"] == backend.label() and extracted["pypdf"] == pypdf.__version__
    assert pdf.pdftotext_backend() is None  # the fixture hid pdftotext: no backend, not an error


def test_a_pdftotext_that_does_not_say_its_version_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: "pdftotext")

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, b"", b"Usage: pdftotext [options] <PDF-file>")

    monkeypatch.setattr("primarysource.readers.pdf.subprocess.run", run)
    assert pdf.pdftotext_backend() == pdf.Backend("pdftotext", "unknown")

    def run_poppler(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 0, b"", b"pdftotext version 99.1.0\nCopyright 2005-2099 Invented")

    monkeypatch.setattr("primarysource.readers.pdf.subprocess.run", run_poppler)
    assert pdf.pdftotext_backend() == pdf.Backend("pdftotext", "99.1.0")


def test_without_pypdf_a_read_is_a_lib_error_naming_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdf", None)
    for call in (lambda: pdf.extract(PDF), pdf.pypdf_backend):
        with pytest.raises(LibError, match="needs pypdf") as raised:
            call()
        assert '"primarysource[' in raised.value.hint


def test_serving_never_imports_pypdf() -> None:
    """The readers and the libraries that serve stored extractions import without touching pypdf (PLAN.md §5.13)."""
    probe = (
        "import sys; import primarysource.readers.pdf, primarysource.readers.bookmarks, primarysource.ecma.library, "
        "primarysource.bbf.library; assert 'pypdf' not in sys.modules, 'pypdf was imported'"
    )
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False)  # noqa: S603
    assert done.returncode == 0, done.stderr
