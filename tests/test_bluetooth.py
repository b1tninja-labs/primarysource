"""bluetooth: catalogue parsing, the paced and pinned fetch, the import, and the shared tools, over invented pages.

No SIG text and no network: the listing, the spec pages and the PDFs are invented, and the fetcher's transport is a
dictionary. The PDFs are `pdffixture.make_pdf` pages with numbered headings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pdffixture import make_pdf

from primarysource import cli, registry
from primarysource.bluetooth import COLLECTION, catalogue, importer
from primarysource.bluetooth.spec import SPEC
from primarysource.errors import LibError
from primarysource.fetch import check_url
from primarysource.pdfcorpus import corpus as pdfcorpus_corpus
from primarysource.pdfcorpus import tools

pytest.importorskip("pypdf")

BASE = "https://www.bluetooth.com/specifications/specs/"


@pytest.fixture(autouse=True)
def _pypdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("primarysource.readers.pdf.shutil.which", lambda _name: None)


def _row(slug: str, title: str, revision: str, status: str = "Adopted", withdrawal: str = "") -> str:
    return (
        f'<tr id="post-1" class="index-item spec-status-adopted spec"><td class="acronym"><span>{title}</span></td>'
        f'<td class="title"><a href="{BASE}{slug}/" target="_self">\n  {title}  </a></td>'
        f'<td class="revision">{revision}</td><td class="type">Specification</td>'
        f'<td class="status">{status}</td><td class="deprecation"></td><td class="withdrawal">{withdrawal}</td></tr>'
    )


LISTING = (
    "<table><thead><tr><th>Document Name</th></tr></thead><tbody>"
    + _row("widget-service", "Widget Service", "1.1")
    + _row("gadget-profile-2-0", "Gadget Profile", "2.0", "Draft")
    + _row("html-only-spec", "HTML Only &amp; Co", "1.0")
    + _row("old-profile", "Old Profile", "1.0", withdrawal="2025-01-01")
    + "</tbody></table>"
)


def _spec_page(pdf_url: str | None, extra: str = "") -> str:
    rows = f'<tr><td>Widget (HTML)</td><td><a href="{pdf_url}">PDF </a></td></tr>' if pdf_url else ""
    tests = (
        "<tr><td>Test Suite (TS)</td><td><a href='https://files.bluetooth.com/download/x-ts-p1-pdf/'>PDF</a></td></tr>"
        "<tr><td>Errata Correction 1</td><td><a href='https://www.bluetooth.org/DocMan/handlers/DownloadDoc.ashx?doc_id=9'>PDF</a></td></tr>"
    )
    return f"<table><tbody><tr><th>Documents</th><th></th></tr>{tests}{rows}{extra}</tbody></table>"


def _pdf(title: str) -> bytes:
    return make_pdf(
        [
            ["1 Introduction", f"The invented {title} text.", "1.1 Scope", "Invented scope quokka sentence."],
            ["2 Requirements", "Invented requirement text.", "2.1 Behaviour", "Invented behaviour sentence."],
        ],
        [],
    )


WIDGET_PDF = "https://www.bluetooth.org/DocMan/handlers/DownloadDoc.ashx?doc_id=1"
GADGET_PDF = "https://files.bluetooth.com/download/gadget-pdf/"


def _transport(served: dict[str, bytes]):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def get(url: str, max_bytes: int) -> bytes:
        calls.append(url)
        if url not in served:
            raise LibError(f"{url}: HTTP 404", "")
        return served[url]

    get.calls = calls  # type: ignore[attr-defined]
    return get


def _served() -> dict[str, bytes]:
    return {
        catalogue.LISTING_URL: LISTING.encode(),
        f"{BASE}widget-service/": _spec_page(WIDGET_PDF).encode(),
        f"{BASE}gadget-profile-2-0/": _spec_page(GADGET_PDF).encode(),
        f"{BASE}html-only-spec/": _spec_page(None).encode(),
        WIDGET_PDF: _pdf("widget"),
        GADGET_PDF: _pdf("gadget"),
    }


# ---- catalogue ------------------------------------------------------------------------------------------------


def test_the_listing_gives_a_slug_title_revision_and_status_per_row() -> None:
    entries = {e.slug: e for e in catalogue.parse_listing(LISTING)}
    assert list(entries) == ["widget-service", "gadget-profile-2-0", "html-only-spec", "old-profile"]
    widget = entries["widget-service"]
    assert (widget.title, widget.revision, widget.status, widget.number) == (
        "Widget Service",
        "1.1",
        "Adopted",
        "Bluetooth Widget Service 1.1",
    )
    assert entries["html-only-spec"].title == "HTML Only & Co"
    assert [entries[s].corpus_status for s in entries] == ["final", "draft", "final", "withdrawn"]


def test_the_spec_pdf_is_the_first_row_that_is_not_a_test_document() -> None:
    assert catalogue.parse_spec_page(_spec_page(WIDGET_PDF)) == WIDGET_PDF
    assert catalogue.parse_spec_page(_spec_page(None)) is None
    assert catalogue.parse_spec_page("<p>nothing</p>") is None


def test_a_listing_with_no_rows_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    fetcher = importer.new_fetcher(_transport({catalogue.LISTING_URL: b"<html>redesigned</html>"}), 0)
    with pytest.raises(LibError, match="layout has changed"):
        importer.refresh_catalogue(tmp_path, fetcher)
    assert not (tmp_path / "catalogue.json").exists()


def test_the_catalogue_is_cached_and_a_missing_one_names_the_command(tmp_path: Path) -> None:
    with pytest.raises(LibError) as raised:
        catalogue.read(tmp_path / "catalogue.json")
    assert raised.value.hint == "primarysource bluetooth catalogue"
    entries = importer.refresh_catalogue(tmp_path, importer.new_fetcher(_transport(_served()), 0))
    assert catalogue.read(tmp_path / "catalogue.json") == entries


def test_select_takes_named_slugs_or_a_status_and_refuses_an_unknown_slug() -> None:
    entries = catalogue.parse_listing(LISTING)
    assert [e.slug for e in importer.select(entries, [])] == ["widget-service", "html-only-spec", "old-profile"]
    assert [e.slug for e in importer.select(entries, [], "draft")] == ["gadget-profile-2-0"]
    assert len(importer.select(entries, [], "any")) == 4
    assert [e.slug for e in importer.select(entries, ["gadget-profile-2-0"])] == ["gadget-profile-2-0"]
    with pytest.raises(LibError, match="not in the catalogue: nope"):
        importer.select(entries, ["nope"])


def test_the_download_page_in_front_of_a_file_is_followed_to_the_pdf(tmp_path: Path) -> None:
    link = GADGET_PDF + "?dlm-dp-dl-force=1&dlm-dp-dl-nonce=abc"
    interstitial = (
        f'<html><body>Your download should start.<a href="{link.replace("&", "&amp;")}">here</a></body></html>'
    )
    assert catalogue.parse_download_page(interstitial) == link
    assert catalogue.parse_download_page("<p>nothing</p>") is None
    served = _served()
    served[GADGET_PDF] = interstitial.encode()
    served[link] = _pdf("gadget")
    report = _run(tmp_path, served, ["gadget-profile-2-0"])
    assert [o.status for o in report.outcomes] == ["imported"]


# ---- fetch and import -----------------------------------------------------------------------------------------


def _run(
    tmp_path: Path, served: dict[str, bytes], slugs: list[str], *, force: bool = False, repin: bool = False
) -> importer.Report:
    entries = importer.select(catalogue.parse_listing(LISTING), slugs, "any")
    fetcher = importer.new_fetcher(_transport(served), 0)
    return importer.fetch_specs(
        SPEC, entries, fetcher, home=tmp_path, root=tmp_path / "corpus", force=force, repin=repin
    )


def test_fetch_stores_the_pdf_pins_it_cuts_at_headings_and_indexes(tmp_path: Path) -> None:
    report = _run(tmp_path, _served(), ["widget-service", "html-only-spec", "gadget-profile-2-0"])
    outcomes = {o.slug: o for o in report.outcomes}
    assert outcomes["widget-service"].status == "imported" and outcomes["widget-service"].sections == 4
    assert outcomes["html-only-spec"].status == "no-pdf"
    assert (tmp_path / "pdf" / "widget-service.pdf").is_file()
    pins = json.loads((tmp_path / "pins.json").read_text(encoding="utf-8"))
    assert set(pins) == {"widget-service", "gadget-profile-2-0"} and len(pins["widget-service"]["sha256"]) == 64
    assert report.indexed_sections == 8
    loaded = pdfcorpus_corpus.load_corpus(SPEC, tmp_path / "corpus")
    assert [d.doc_id for d in loaded.documents] == ["gadget-profile-2-0", "widget-service"]
    assert "Bluetooth Widget Service 1.1" in tools.info(loaded, "bluetooth:widget-service")
    assert "quokka" in tools.search(loaded, "quokka", doc="widget-service")
    read = tools.read(loaded, "bluetooth:widget-service§1.1")
    assert "Invented scope quokka sentence." in read and "cite: Bluetooth Widget Service 1.1 §1.1" in read
    assert "status is 'draft'" in tools.read(loaded, "gadget-profile-2-0§2.1")


def test_what_is_imported_is_not_fetched_again_unless_forced(tmp_path: Path) -> None:
    _run(tmp_path, _served(), ["widget-service"])
    transport_served = _served()
    again = _run(tmp_path, transport_served, ["widget-service"])
    assert [o.status for o in again.outcomes] == ["unchanged"]
    forced = _run(tmp_path, transport_served, ["widget-service"], force=True)
    assert [o.status for o in forced.outcomes] == ["imported"]


def test_a_pdf_that_changed_since_it_was_pinned_is_refused_until_repinned(tmp_path: Path) -> None:
    _run(tmp_path, _served(), ["widget-service"])
    revised = _served()
    revised[WIDGET_PDF] = make_pdf([["1 Introduction", "Replaced invented text.", "1.1 Scope", "More."]], [])
    refused = _run(tmp_path, revised, ["widget-service"], force=True)
    assert refused.outcomes[0].status == "changed" and "--repin" in refused.outcomes[0].note
    loaded = pdfcorpus_corpus.load_corpus(SPEC, tmp_path / "corpus")
    assert "quokka" in tools.search(loaded, "quokka")  # the old text still serves
    accepted = _run(tmp_path, revised, ["widget-service"], force=True, repin=True)
    assert accepted.outcomes[0].status == "imported"


def test_a_failed_document_is_reported_and_the_rest_go_on(tmp_path: Path) -> None:
    served = _served()
    del served[GADGET_PDF]
    served[f"{BASE}old-profile/"] = _spec_page(
        "https://www.bluetooth.org/DocMan/handlers/DownloadDoc.ashx?doc_id=5"
    ).encode()
    served["https://www.bluetooth.org/DocMan/handlers/DownloadDoc.ashx?doc_id=5"] = b"<html>login</html>"
    report = _run(tmp_path, served, ["gadget-profile-2-0", "old-profile", "widget-service"])
    outcomes = {o.slug: o for o in report.outcomes}
    assert outcomes["gadget-profile-2-0"].status == "failed" and "404" in outcomes["gadget-profile-2-0"].note
    assert outcomes["old-profile"].status == "failed" and "not a PDF" in outcomes["old-profile"].note
    assert outcomes["widget-service"].status == "imported"
    assert not (tmp_path / "pdf" / "old-profile.pdf").exists()


def test_requests_are_paced_and_only_to_the_sigs_hosts() -> None:
    from primarysource.fetch import Fetcher

    slept: list[float] = []
    now = [0.0]
    fetcher = Fetcher(
        catalogue.HOSTS,
        _transport({catalogue.LISTING_URL: b"x"}),
        min_interval=importer.CRAWL_DELAY,
        clock=lambda: now[0],
        sleep=slept.append,
        collection="bluetooth",
    )
    fetcher.get(catalogue.LISTING_URL, 10)
    fetcher.get(catalogue.LISTING_URL, 10)
    assert slept == [importer.CRAWL_DELAY]
    with pytest.raises(LibError):
        fetcher.get("https://example.com/spec.pdf", 10)
    assert importer.CRAWL_DELAY == 10.0


# ---- wiring ---------------------------------------------------------------------------------------------------


def test_the_collection_is_registered_and_serves_the_five_prefixed_tools() -> None:
    assert "bluetooth" in registry.available()
    assert registry.load("bluetooth") is COLLECTION
    served = {t.name for t in cli.build_server(["bluetooth"])._tool_manager.list_tools()}
    assert served == {f"bluetooth_{tool}" for tool in ("search", "read", "outline", "info", "cite")}
    ref = COLLECTION.grammar.parse("bluetooth:battery-service§3.1")
    assert (ref.doc, ref.section) == ("battery-service", "3.1")


def test_the_commands_list_dry_run_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_BLUETOOTH_HOME", str(tmp_path))
    monkeypatch.delenv("PRIMARYSOURCE_BLUETOOTH_CORPUS", raising=False)
    assert cli.main(["bluetooth", "list"]) == 2  # no catalogue yet
    assert "primarysource bluetooth catalogue" in capsys.readouterr().err
    catalogue.write(tmp_path / "catalogue.json", catalogue.parse_listing(LISTING))
    assert cli.main(["bluetooth", "list", "--status", "draft"]) == 0
    assert "gadget-profile-2-0  Gadget Profile 2.0  [Draft]" in capsys.readouterr().out
    assert cli.main(["bluetooth", "fetch", "--dry-run"]) == 0
    assert "would fetch up to 3 documents" in capsys.readouterr().out
    assert not (tmp_path / "pdf").exists()
    assert cli.main(["bluetooth", "fetch", "nope"]) == 2
    assert cli.main(["bluetooth", "index"]) == 2  # nothing imported yet: the error names the fetch command
    assert "action: primarysource bluetooth fetch" in capsys.readouterr().err


def test_fetch_honours_the_offline_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_NETWORK", "offline")
    fetcher = importer.new_fetcher(None, 0)
    with pytest.raises(LibError, match="offline"):
        fetcher.get(catalogue.LISTING_URL, 10)


# ---- the two supplements: GATT Specification Supplement and Assigned Numbers ----------------------------------

GSS_PAGES = [
    "1 Introduction",
    "Invented introduction sentence.",
    "2 Conventions",
    "Invented convention sentence.",
    "2.1 Data Types",
    "Invented data type sentence.",
    "3 Characteristics",
    "Invented characteristic sentence about blood pressure.",
    "3.1 Acceleration",
    "Invented sensor sentence.",
    "4 Descriptors",
    "Invented descriptor introduction.",
    "4.1 Valid Range",
    "Invented range sentence.",
]


def test_the_supplements_carry_their_sig_addresses_and_versions() -> None:
    by_slug = {e.slug: e for e in catalogue.SUPPLEMENTS}
    gss = by_slug["gatt-specification-supplement"]
    assert (gss.revision, gss.page, gss.pdf) == ("2026-09-09", catalogue.GSS_PAGE, catalogue.GSS_PDF)
    an = by_slug["assigned-numbers"]
    assert (an.revision, an.page, an.pdf) == ("2026-11-16", catalogue.AN_PAGE, catalogue.AN_PDF)
    for entry in catalogue.SUPPLEMENTS:
        check_url(entry.pdf, catalogue.HOSTS)
        assert entry.corpus_status == "published"
    assert gss.number == "Bluetooth GATT Specification Supplement 2026-09-09"
    assert an.number == "Bluetooth Assigned Numbers 2026-11-16"
    assert importer.select(catalogue.SUPPLEMENTS, []) == []  # `fetch` with no slugs does not take them
    assert len(importer.select(catalogue.SUPPLEMENTS, [], "any")) == 2


def test_the_supplements_are_added_to_the_listing_and_round_trip_through_the_cache(tmp_path: Path) -> None:
    entries = importer.refresh_catalogue(tmp_path, importer.new_fetcher(_transport(_served()), 0))
    slugs = [e.slug for e in entries]
    assert slugs[-2:] == ["gatt-specification-supplement", "assigned-numbers"]
    assert catalogue.read(tmp_path / "catalogue.json") == entries
    assert catalogue.read(tmp_path / "catalogue.json")[-1].clauses == catalogue.AN_CLAUSES
    catalogue.write(tmp_path / "again.json", list(catalogue.SUPPLEMENTS))
    assert catalogue.read(tmp_path / "again.json") == list(catalogue.SUPPLEMENTS)


def test_a_supplement_is_fetched_from_its_pdf_address_and_only_its_clauses_are_kept(tmp_path: Path) -> None:
    pdf = make_pdf([GSS_PAGES], [])
    transport = _transport({catalogue.GSS_PDF: pdf})
    fetcher = importer.new_fetcher(transport, 0)
    entries = [e for e in catalogue.SUPPLEMENTS if e.slug == "gatt-specification-supplement"]
    report = importer.fetch_specs(SPEC, entries, fetcher, home=tmp_path, root=tmp_path / "corpus")
    assert [o.status for o in report.outcomes] == ["imported"]
    assert transport.calls == [catalogue.GSS_PDF]  # the SIG's page is not read: its PDF address is in the catalogue
    text = (tmp_path / "corpus" / "text" / "gatt-specification-supplement.txt").read_text(encoding="utf-8")
    assert "Invented range sentence." in text and "Invented data type sentence." in text
    assert "blood pressure" not in text and "Invented sensor sentence." not in text  # §3 is read past
    record = json.loads((tmp_path / "corpus" / "install.json").read_text(encoding="utf-8"))
    kept = record["documents"]["gatt-specification-supplement"]
    assert (kept["version"], kept["source"], kept["sections_left_out"]) == (
        "2026-09-09",
        catalogue.GSS_PDF,
        3,
    )
    loaded = pdfcorpus_corpus.load_corpus(SPEC, tmp_path / "corpus")
    assert "Invented range sentence." in tools.read(loaded, "bluetooth:gatt-specification-supplement§4.1")


def test_a_clause_the_pdf_does_not_have_is_refused() -> None:
    with pytest.raises(LibError, match="none of the clauses"):
        importer._cut(["1 Introduction\nText.\n"], ("9",))


def test_a_heading_the_splitter_misses_is_found_by_its_exact_line_and_a_contents_row_is_not() -> None:
    pages = [
        "1 Introduction\nIntro text.\n2 Core\nCore text.\n2.1 Sub\nSub text.\n"
        "3.6 Declarations . . . . . . 9\n"
        "3.6 Declarations\nDeclaration text.\n3.7 Descriptors UUID\nDescriptor text.\n"
    ]
    lines, sections, left_out = importer._cut(
        pages, ("3.6", "3.7"), (("3.6", "Declarations"), ("3.7", "Descriptors"))
    )
    assert [s.id for s in sections] == ["3.6", "3.7"] and left_out == 3
    assert lines[sections[0].start_line - 1] == "3.6 Declarations"
    assert "Declaration text." in lines and "Descriptor text." in lines and "Intro text." not in lines
    with pytest.raises(LibError, match="is not in the PDF"):
        importer._cut(pages, ("3.8",), (("3.8", "Characteristics"),))
