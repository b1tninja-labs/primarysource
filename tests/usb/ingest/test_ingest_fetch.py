"""sha256 logic, the sources parser, the index writer and the fetch orchestration (no network)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from primarysource.usb.ingest import fetch
from primarysource.usb.ingest.fetch import (
    FetchError,
    check_digest,
    obtain_pdf,
    parse_from_files,
    run,
)
from primarysource.usb.ingest.index import read_index, sha256_bytes, sha256_file, write_index
from primarysource.usb.ingest.sources import Source, SourcesError, parse_sources
from primarysource.usb.models import Document, Section

GOOD = """
[[source]]
doc_id = "a-1"
number = "NIST X 1"
title = "T"
date = "2024-07"
status = "final"
url = "https://example.test/a.pdf"
"""
PDF = b"%PDF-1.6 fake body"


def doc(sections: tuple[Section, ...] = ()) -> Document:
    return Document(
        "a-1",
        "NIST X 1",
        "T",
        "2024-07",
        "final",
        "https://example.test/a.pdf",
        "ab" * 32,
        "a-1.txt",
        sections,
    )


# --- sha256 -------------------------------------------------------------------------------------------


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"x" * 3_000_000)
    assert sha256_file(path) == hashlib.sha256(b"x" * 3_000_000).hexdigest()
    assert sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_check_digest_rejects_mismatch_and_accepts_unrecorded() -> None:
    with pytest.raises(FetchError, match="does not match"):
        check_digest("a-1", "aa", "bb")
    check_digest("a-1", "aa", "aa")
    check_digest("a-1", "aa", "")  # nothing recorded: accepted, caller records it


# --- sources parser -----------------------------------------------------------------------------------


def test_parse_sources_reads_fields() -> None:
    (source,) = parse_sources(GOOD)
    assert source == Source(
        "a-1", "https://example.test/a.pdf", "NIST X 1", "T", "2024-07", "final", ""
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda t: t.replace('date = "2024-07"', 'date = "2024-13"'), "YYYY-MM"),
        (lambda t: t.replace("https://", "http://"), "https"),
        (lambda t: t.replace('doc_id = "a-1"', 'doc_id = "A 1"'), "slug"),
        (lambda t: t.replace('status = "final"\n', ""), "status"),
        (lambda t: t + 'bogus = "1"\n', "unknown"),
        (lambda t: t + 'sha256 = "xyz"\n', "sha256"),
        (lambda t: t + GOOD, "duplicate"),
        (lambda t: "not [ toml", "not valid TOML"),
        (lambda t: "", r"no \[\[source\]\]"),
    ],
)
def test_parse_sources_rejects_bad_input(mutation: object, message: str) -> None:
    assert callable(mutation)
    with pytest.raises(SourcesError, match=message):
        parse_sources(mutation(GOOD))


def test_shipped_sources_toml_parses() -> None:
    from primarysource.usb.paths import PACKAGE_DATA

    path = PACKAGE_DATA / "sources.toml"
    sources = parse_sources(path.read_text(encoding="utf-8"))
    by_id = {s.doc_id: s for s in sources}
    assert by_id["usb-ccid-1-1"].number == "USB-IF CCID Rev 1.1"
    assert by_id["usb-ccid-1-1"].date == "2005-04"


# --- index writer -------------------------------------------------------------------------------------


def test_index_round_trip_and_shape(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    original = doc((Section("3.2.4", "GENERAL AUTHENTICATE Card Command", 10, 20),))
    write_index(path, [original])
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema"] == 1
    assert raw["documents"][0]["sections"][0] == {
        "id": "3.2.4",
        "heading": "GENERAL AUTHENTICATE Card Command",
        "start_line": 10,
        "end_line": 20,
    }
    assert set(raw["documents"][0]) == {
        "doc_id", "number", "title", "date", "status", "url", "sha256", "text_file", "sections",
    }  # fmt: skip
    assert read_index(path) == [original]
    assert not (tmp_path / "index.json.tmp").exists()


def test_read_index_tolerates_missing_corrupt_and_foreign_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "index.json"
    assert read_index(path) == []
    path.write_text("{oops", encoding="utf-8")
    assert read_index(path) == []
    path.write_text('{"schema": 2, "documents": []}', encoding="utf-8")
    assert read_index(path) == []


# --- obtain_pdf / run ---------------------------------------------------------------------------------


def source(sha: str = "") -> Source:
    return Source(
        "a-1", "https://example.test/a.pdf", "NIST X 1", "T", "2024-07", "final", sha
    )


def test_obtain_pdf_skips_download_when_present_and_hash_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a-1.pdf").write_bytes(PDF)
    monkeypatch.setattr(fetch, "download", lambda url: pytest.fail("must not download"))
    assert obtain_pdf(source(), tmp_path, sha256_bytes(PDF), None) == sha256_bytes(PDF)


def test_obtain_pdf_redownloads_on_mismatch_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a-1.pdf").write_bytes(b"%PDF-stale")
    monkeypatch.setattr(fetch, "download", lambda url: PDF)
    digest = obtain_pdf(source(sha256_bytes(PDF)), tmp_path, sha256_bytes(PDF), None)
    assert digest == sha256_bytes(PDF)
    assert (tmp_path / "a-1.pdf").read_bytes() == PDF


def test_obtain_pdf_refuses_download_with_wrong_digest_and_keeps_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "download", lambda url: PDF)
    with pytest.raises(FetchError, match="does not match"):
        obtain_pdf(source("0" * 64), tmp_path, "0" * 64, None)
    assert not (tmp_path / "a-1.pdf").exists()


def test_obtain_pdf_from_file_needs_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fetch, "download", lambda url: pytest.fail("must not download"))
    src = tmp_path / "mine.pdf"
    src.write_bytes(PDF)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    assert obtain_pdf(source(), corpus, "", src) == sha256_bytes(PDF)
    assert (corpus / "a-1.pdf").read_bytes() == PDF
    with pytest.raises(FetchError, match="does not match"):
        obtain_pdf(source("1" * 64), corpus, "1" * 64, src)


def test_obtain_pdf_from_file_rejects_non_pdf(tmp_path: Path) -> None:
    src = tmp_path / "x.pdf"
    src.write_bytes(b"<html>")
    with pytest.raises(FetchError, match="not a PDF"):
        obtain_pdf(source(), tmp_path, "", src)


def test_parse_from_files() -> None:
    assert parse_from_files(["a=/x/y.pdf"]) == {"a": Path("/x/y.pdf")}
    with pytest.raises(SourcesError):
        parse_from_files(["nopath"])


def test_run_records_digest_and_writes_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "sources.toml").write_text(GOOD, encoding="utf-8")
    pdf = tmp_path / "mine.pdf"
    pdf.write_bytes(PDF)
    monkeypatch.setattr(fetch, "find_pdftotext", lambda: "pdftotext")
    monkeypatch.setattr(
        fetch, "extract_text", lambda _pdf: "1. Intro\nbody\n2. Next\nbody\n"
    )
    assert run(tmp_path, {"a-1": pdf}, []) == 0
    (indexed,) = read_index(tmp_path / "corpus" / "index.json")
    assert indexed.sha256 == sha256_bytes(PDF)
    assert indexed.text_file == "a-1.txt"
    assert [s.id for s in indexed.sections] == ["1", "2"]
    assert (
        (tmp_path / "corpus" / "a-1.txt")
        .read_text(encoding="utf-8")
        .startswith("1. Intro")
    )
    # A second run with a tampered PDF and no pinned digest redownloads against the recorded one and fails.
    (tmp_path / "corpus" / "a-1.pdf").write_bytes(b"%PDF-tampered")
    monkeypatch.setattr(fetch, "download", lambda url: b"%PDF-other")
    assert run(tmp_path, {}, []) == 1
    assert "does not match the recorded" in capsys.readouterr().err


def test_a_fetch_builds_the_search_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from primarysource.pdfcorpus import fts, tools
    from primarysource.usb.server.corpus import load_corpus

    (tmp_path / "sources.toml").write_text(GOOD, encoding="utf-8")
    pdf = tmp_path / "mine.pdf"
    pdf.write_bytes(PDF)
    monkeypatch.setattr(fetch, "find_pdftotext", lambda: "pdftotext")
    monkeypatch.setattr(
        fetch, "extract_text", lambda _pdf: "1. Intro\nbody\n2. Next\nwombat text\n"
    )
    assert run(tmp_path, {"a-1": pdf}, []) == 0
    assert "indexed 2 section(s)" in capsys.readouterr().out
    corpus = load_corpus(tmp_path / "corpus")
    assert (tmp_path / "corpus" / fts.INDEX_FILE).is_file()
    assert "a-1§2" in tools.search(corpus, "wombat")


def test_run_rejects_unknown_doc_id(tmp_path: Path) -> None:
    (tmp_path / "sources.toml").write_text(GOOD, encoding="utf-8")
    with pytest.raises(SourcesError, match="not in sources.toml"):
        run(tmp_path, {}, ["nope"])
