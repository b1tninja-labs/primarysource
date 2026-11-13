"""Publication status from the CSRC listing, the OSCAL history and PDF front matter. Synthetic inputs only."""

from __future__ import annotations

from primarysource.nist.ingest.status import (
    DocumentStatus,
    Release,
    csrc_number_for,
    default_documents,
    pdf_marked_draft,
)


def test_corpus_ids_map_to_csrc_numbers() -> None:
    assert csrc_number_for("sp800-53r5") == "800-53 Rev. 5"
    assert csrc_number_for("sp800-53r5-oscal") == "800-53 Rev. 5"
    assert csrc_number_for("sp800-172r3") == "800-172 Rev. 3"
    assert csrc_number_for("sp800-218") == "800-218"
    assert csrc_number_for("sp800-218a") == "800-218A"


def test_front_matter_draft_marker() -> None:
    assert pdf_marked_draft("Initial Public Draft\nSP 800-99 ...")
    assert not pdf_marked_draft("NIST SP 800-53 Rev. 5\nSeptember 2020\nFinal")


def _status(doc_id: str, number: str, current: bool, release: str | None) -> DocumentStatus:
    return DocumentStatus(
        doc_id=doc_id,
        csrc_number=number,
        csrc_status="Final",
        csrc_current=current,
        latest_release=Release(release, "2025-08-26") if release else None,
        pdf_marked_draft=None,
        oscal_status=None,
    )


def test_default_is_newest_document_of_the_current_final_publication() -> None:
    statuses = [
        _status("sp800-53r5", "800-53 Rev. 5", True, None),
        _status("sp800-53r5-oscal", "800-53 Rev. 5", True, "5.2.0"),
        _status("sp800-53r5-high-oscal", "800-53 Rev. 5", True, "5.2.0"),
        _status("sp800-53r4", "800-53 Rev. 4", False, None),
    ]
    assert [s.doc_id for s in default_documents(statuses)] == ["sp800-53r5-oscal"]


def test_publication_not_marked_current_has_no_default() -> None:
    statuses = [_status("sp800-53r4", "800-53 Rev. 4", False, None)]
    assert default_documents(statuses) == []


def test_bare_publication_number_resolves_to_its_default_revision() -> None:
    from pathlib import Path

    from primarysource.nist.models import Document
    from primarysource.nist.server.corpus import Corpus
    from primarysource.nist.server.tools import resolve_doc

    def doc(doc_id: str) -> Document:
        return Document(
            doc_id=doc_id,
            number=f"NIST {doc_id}",
            title=doc_id,
            date="2020-12",
            status="final",
            url="https://example.invalid/",
            sha256="0" * 64,
            text_file=f"{doc_id}.txt",
            sections=(),
        )

    corpus = Corpus(
        root=Path("."),
        documents=(doc("sp800-53r5"), doc("sp800-53r5-oscal")),
        defaults={"800-53": "sp800-53r5-oscal"},
    )
    assert resolve_doc(corpus, "NIST SP 800-53").doc_id == "sp800-53r5-oscal"
    assert resolve_doc(corpus, "sp800-53r5").doc_id == "sp800-53r5"  # an explicit id still wins


def test_baseline_and_framework_aliases_are_defaults() -> None:
    from primarysource.nist.ingest.status import compute_defaults

    low = DocumentStatus(
        doc_id="sp800-53r5-low-oscal",
        csrc_number="800-53 Rev. 5",
        csrc_status="Final",
        csrc_current=True,
        latest_release=None,
        pdf_marked_draft=None,
        oscal_status="final",
        variant="low",
    )
    csf = DocumentStatus(
        doc_id="csf2-oscal",
        csrc_number=None,
        csrc_status=None,
        csrc_current=False,
        latest_release=None,
        pdf_marked_draft=None,
        oscal_status="final",
        framework="CSF",
    )
    assert compute_defaults([low, csf]) == {"800-53 low": "sp800-53r5-low-oscal", "csf": "csf2-oscal"}
