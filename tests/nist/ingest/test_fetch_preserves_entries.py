"""fetch.run keeps index entries it does not own, such as the -oscal catalogues, instead of dropping them."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from primarysource.nist.ingest import fetch
from primarysource.nist.ingest.fetch import run
from primarysource.nist.ingest.index import read_index, write_index
from primarysource.nist.models import Document, Section

SOURCES = """
[[source]]
doc_id = "a-1"
number = "NIST X 1"
title = "T"
date = "2024-07"
status = "final"
url = "https://example.test/a.pdf"
"""


def foreign(text_file: str) -> Document:
    return Document(
        "cat-oscal",
        "NIST CAT",
        "A catalogue not in sources.toml",
        "2024-07",
        "final",
        "https://example.test/cat.xml",
        "cd" * 32,
        text_file,
        (Section(id="ac-1", heading="Policy", start_line=1, end_line=1),),
    )


def test_entry_absent_from_sources_survives_a_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (tmp_path / "sources.toml").write_text(SOURCES, encoding="utf-8")
    (corpus / "cat-oscal.txt").write_text("ac-1 Policy\n", encoding="utf-8")
    (corpus / "gone-oscal.txt").write_text("x\n", encoding="utf-8")
    kept = foreign("cat-oscal.txt")
    orphan = replace(kept, doc_id="gone-oscal", text_file="missing.txt")
    write_index(corpus / "index.json", [kept, orphan])
    pdf = tmp_path / "mine.pdf"
    pdf.write_bytes(b"%PDF-1.6 fake body")
    monkeypatch.setattr(fetch, "find_pdftotext", lambda: "pdftotext")
    monkeypatch.setattr(fetch, "extract_text", lambda _pdf: "1. Intro\nbody\n")

    assert run(tmp_path, {"a-1": pdf}, []) == 0

    by_id = {d.doc_id: d for d in read_index(corpus / "index.json")}
    assert set(by_id) == {"a-1", "cat-oscal"}
    assert by_id["cat-oscal"] == kept
