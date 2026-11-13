from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import zimfixture
from zimfixture import build_zim, shell

from primarysource.zim import _libzim, library, service
from primarysource.zim.errors import ZimloreError

BOOK = "acme_en_widgets"


def test_listing_resolving_and_missing_libraries(acme: Path) -> None:
    listing = service.libraries()
    assert [row["name"] for row in listing["libraries"]] == [BOOK]
    row = listing["libraries"][0]
    assert row["search"] == "full-text" and row["freshness"]["date"] == "2026-10-01"
    assert "stale_after_days" not in row["freshness"], "a constant is stated once, in the server instructions"
    assert set(row) == {"name", "title", "language", "articles", "size_bytes", "search", "freshness", "provenance"}
    assert (listing["total"], listing["truncated"]) == (1, False)
    assert service.libraries(verbose=True)["libraries"][0]["license"] is None, "an unstated licence is null"
    resolved = service.resolve("widgets")
    assert resolved["name"] == BOOK and resolved["version"]["pinned_by"] == "ZIM edition date"
    assert "release number" in resolved["version"]["note"]


def test_no_library_is_an_error_not_an_empty_result(home: Path) -> None:
    calls: list[Callable[[], object]] = [
        service.libraries,
        lambda: service.search("anything"),
        lambda: service.read("x§y"),
    ]
    for call in calls:
        with pytest.raises(ZimloreError) as caught:
            call()
        assert "no ZIM files found" in caught.value.message and caught.value.hint


def test_search_finds_by_body_and_by_title_and_cites(acme: Path) -> None:
    body = service.search("kettle", "acme")
    assert body["hits"] == [] or body["hits"][0]["ref"].startswith(f"{BOOK}§")
    hits = service.search("timeout flange spin", "acme")["hits"]
    assert hits[0]["ref"] == f"{BOOK}§guide/config"
    assert "timeout setting bounds" in hits[0]["excerpt"], "the excerpt is the block that matches, not the intro"
    assert "cite" not in hits[0] and "edition" not in hits[0], "the citation is built once, by zim_cite, not per hit"
    assert service.search("timeout flange spin", "acme")["editions"] == {BOOK: "2026-10-01"}
    assert service.cite(hits[0]["ref"])["cite"].startswith(
        "Acme Widgets Docs [acme_en_widgets], ZIM edition 2026-10-01, entry guide/config"
    )
    title = service.search("Installing Acme Widgets", "acme")["hits"][0]
    assert title["ref"] == f"{BOOK}§guide/install"


def test_search_folds_redirects_and_skips_stylesheets(acme: Path) -> None:
    refs = [h["ref"] for h in service.search("install widgets acme", "acme", limit=20)["hits"]]
    assert len(refs) == len(set(refs))
    assert all(not ref.endswith(".css") and "old/install" not in ref for ref in refs)


def test_empty_result_says_it_is_the_search_that_found_nothing(acme: Path) -> None:
    result = service.search("zzqxj", "acme")
    assert result["hits"] == [] and "not proof" in result["note"]
    with pytest.raises(ZimloreError, match="empty query"):
        service.search("   ")


def test_search_budget_truncates_and_says_so(acme: Path) -> None:
    full = service.search("widget", "acme", limit=10, max_tokens=5000)
    assert len(full["hits"]) >= 2
    tight = service.search("widget", "acme", limit=10, max_tokens=1)
    assert len(tight["hits"]) == 1 and tight["truncated"] is True, "one hit always survives, and the cut is reported"


def test_library_without_a_fulltext_index_is_searched_by_title_and_says_so(home: Path) -> None:
    build_zim(home / "zim", "titles.zim", name="titles_only", title="Titles Only", fulltext=False)
    result = service.search("Installing", "titles_only")
    assert result["hits"][0]["ref"] == "titles_only§guide/install"
    assert result["hits"][0]["match"] == "title"
    assert "no full-text index" in result["title_only"]
    assert service.search("sprockets", "titles_only")["hits"] == [], "body words are invisible without an index"


def test_search_across_libraries_interleaves_and_admits_it(acme: Path) -> None:
    build_zim(acme / "zim", "other.zim", name="other_en_gadgets", title="Gadgets", date="2026-09-01")
    result = service.search("widget", limit=6)
    assert set(result["libraries_searched"]) == {BOOK, "other_en_gadgets"}
    assert {h["ref"].split("§")[0] for h in result["hits"]} == {BOOK, "other_en_gadgets"}
    assert "no comparable score" in result["ranking"]


def test_read_converts_follows_redirects_and_cites(acme: Path) -> None:
    page = service.read("acme§old/install", max_tokens=500)
    assert page["redirected_from"] == "old/install"
    assert page["ref"] == f"{BOOK}§guide/install"
    assert page["content"].startswith("# Installing Acme Widgets")
    assert page["freshness"]["date"] == "2026-10-01" and "edition" not in page
    assert "page_title" not in page, "shown only when the HTML title differs from the entry title"
    assert service.read("acme")["page_title"] == "Acme", (
        "the main page: entry title 'Acme Widgets', HTML title 'Acme'"
    )
    assert page["images"].startswith("1 image")


def test_read_accepts_a_bare_path_with_a_library(acme: Path) -> None:
    assert service.read("guide/config", "acme")["ref"] == f"{BOOK}§guide/config"
    assert service.read("acme")["title"] == "Acme Widgets", "a library alone reads its main page"


def test_paging_follows_next_and_loses_nothing(acme: Path) -> None:
    whole = service.read("acme§guide/config", max_tokens=100_000)
    assert whole["next"] is None
    pieces: list[str] = []
    start, pages = 1, 0
    while True:
        page = service.read("acme§guide/config", start=start, max_tokens=60)
        pieces.append(page["content"])
        pages += 1
        if page["next"] is None:
            break
        assert page["next"]["start"] == page["blocks"]["to"] + 1
        start = page["next"]["start"]
    assert pages > 3, "a 60-token budget must really page this article"
    assert "\n\n".join(pieces).replace("\n- ", "\n\n- ") == whole["content"].replace("\n- ", "\n\n- ")
    assert sum(p.count("Paragraph ") for p in pieces) == 40


def test_a_page_always_makes_progress_when_one_block_exceeds_the_budget(acme: Path) -> None:
    first = service.read("acme§dump", max_tokens=10)
    assert first["content"] == "# Dump" and first["next"]["start"] == 2, "the heading fits; the log block does not"
    huge = service.read("acme§dump", start=first["next"]["start"], max_tokens=10)
    assert huge["blocks"] == {"from": 2, "to": 2, "of": 3}
    assert huge["content"].count("line of a very long log") == 400, "the oversized block is whole, never cut"
    assert "exceeds the budget" in huge["oversize"] and huge["next"]["start"] == 3
    assert "After the dump." in service.read("acme§dump", start=3, max_tokens=10)["content"]


def test_section_read_stops_at_the_next_heading(acme: Path) -> None:
    section = service.read("acme§guide/config#timeouts")
    assert section["scope"] == "section"
    assert section["content"].startswith("## Timeouts") and "--timeout 30" in section["content"]
    assert "## API" not in section["content"]
    assert section["cite"].endswith("entry guide/config#timeouts")


def test_definition_read_is_one_api_entry(acme: Path) -> None:
    definition = service.read("acme§guide/config#widget.run")
    assert "widget.run(speed)" in definition["content"] and "widget.stop" not in definition["content"]


def test_block_read_and_plain_text(acme: Path) -> None:
    block = service.read("acme§guide/install¶2")
    assert block["scope"] == "block" and block["blocks"] == {"from": 1, "to": 1, "of": 1}
    assert block["cite"].endswith("¶2")
    plain = service.read("acme§guide/install#quickstart", format="text")
    assert "```" not in plain["content"] and "widget.run()" in plain["content"] and "##" not in plain["content"]
    with pytest.raises(ZimloreError, match="no ¶999"):
        service.read("acme§guide/install¶999")
    with pytest.raises(ZimloreError, match="unknown format"):
        service.read("acme§guide/install", format="html")


def test_unknown_entry_and_anchor_errors_name_the_alternatives(acme: Path) -> None:
    with pytest.raises(ZimloreError) as entry:
        service.read("acme§guide/instal")
    assert "has no entry" in entry.value.message and "zimlore search" in entry.value.hint
    assert f"{BOOK}§guide/install" in entry.value.extra["did_you_mean"]  # type: ignore[operator]
    with pytest.raises(ZimloreError) as anchor:
        service.read("acme§guide/config#timeout")
    assert anchor.value.extra["did_you_mean"][0] == f"{BOOK}§guide/config#timeouts"  # type: ignore[index]


def test_non_text_entries_are_refused_with_their_type(acme: Path) -> None:
    with pytest.raises(ZimloreError) as caught:
        service.read("acme§blob.bin")
    assert caught.value.extra["mimetype"] == "application/octet-stream"
    assert "second note about sprockets" in service.read("acme§notes.txt")["content"]


def test_article_outline_lists_headings_and_definitions_with_anchors(acme: Path) -> None:
    out = service.outline("acme§guide/config")
    rows = out["outline"]
    by_text = {r["text"]: r for r in rows}
    assert out["ref"] == f"{BOOK}§guide/config", "the page ref is stated once; a row's ref is that plus #anchor"
    assert by_text["Timeouts"] == {"text": "Timeouts", "level": 2, "anchor": "timeouts"}
    assert by_text["`widget.run(speed)`"] == {
        "text": "`widget.run(speed)`",
        "kind": "definition",
        "anchor": "widget.run",
    }
    assert all("ref" not in r for r in rows), "repeating library and path on every row cost ~60 characters each"
    assert service.read(f"{out['ref']}#{by_text['Timeouts']['anchor']}")["scope"] == "section", "ref + #anchor reads"
    paged = service.outline("acme§guide/config", limit=2)
    assert len(paged["outline"]) == 2 and paged["next"] == {"start": 2}


def test_library_outline_pages_by_path_and_filters_by_prefix(acme: Path) -> None:
    everything = service.outline("acme", limit=100)
    paths = [e["ref"].split("§")[1] for e in everything["entries"]]
    assert paths == sorted(paths) and "application.css" not in paths and "blob.bin" not in paths
    assert "guide/install" in paths and "old/install" not in paths, "redirects are listed by their target only"
    first = service.outline("acme", limit=2)
    second = service.outline("acme", start=first["next"]["start"], limit=100)
    joined = [e["ref"] for e in first["entries"] + second["entries"]]
    assert joined == [e["ref"] for e in everything["entries"]], "paging neither skips nor repeats entries"
    scoped = service.outline("acme", prefix="guide/")
    assert [e["ref"].split("§")[1] for e in scoped["entries"]] == ["guide/config", "guide/install"]
    assert "next" not in scoped


def test_links_resolve_and_flag_targets_missing_from_the_zim(acme: Path) -> None:
    rows = {r["text"]: r for r in service.links("acme§guide/install")["links"]}
    assert rows["timeouts"]["ref"] == f"{BOOK}§guide/config#timeouts" and rows["timeouts"]["in_zim"] is True
    assert rows["archived elsewhere"]["in_zim"] is False, "a dangling internal link is reported, not dropped"
    assert rows["the project"] == {"text": "the project", "url": "https://example.org/acme", "external": True}
    assert "NAVLINK" not in rows
    assert rows["timeouts"]["external"] is False and rows["archived elsewhere"]["external"] is False


def test_two_links_to_one_page_with_different_anchors_are_both_reported(home: Path) -> None:
    page = shell(
        "<p><a href='config#timeouts'>config</a> <a href='config#api'>config</a> "
        "<a href='config#api'>config</a> <a href='config'>config</a></p>"
    )
    build_zim(home / "zim", extra={"guide/pointers": page})
    rows = service.links("acme§guide/pointers")["links"]
    assert [r["ref"] for r in rows] == [
        f"{BOOK}§guide/config#timeouts",
        f"{BOOK}§guide/config#api",
        f"{BOOK}§guide/config",
    ], "same text and page, different anchors: distinct; an exact repeat collapses"


def test_cite_carries_edition_freshness_and_licence_note(home: Path) -> None:
    build_zim(home / "zim", license_text="CC-BY-SA-4.0")
    cited = service.cite("acme§guide/config#timeouts")
    assert cited["cite"] == "Acme Widgets Docs [acme_en_widgets], ZIM edition 2026-10-01, entry guide/config#timeouts"
    assert cited["license"] == "CC-BY-SA-4.0" and cited["uuid"]
    with pytest.raises(ZimloreError, match="no section"):
        service.cite("acme§guide/config#nope")


def test_cite_names_the_source_the_zim_declares(home: Path) -> None:
    build_zim(home / "zim", source="https://example.org/acme-docs")
    assert service.cite("acme§guide/config")["cite"].endswith(
        "entry guide/config; source https://example.org/acme-docs"
    )
    assert service.cite("acme§guide/config#timeouts")["cite"].endswith(
        "entry guide/config#timeouts; source https://example.org/acme-docs"
    )


def test_a_cite_without_a_declared_source_has_no_source_clause(acme: Path) -> None:
    assert "source" not in service.cite("acme§guide/config")["cite"]


def test_unstated_licence_says_to_check_upstream(acme: Path) -> None:
    assert "not stated in the ZIM" in service.cite("acme§guide/config")["license"]


@pytest.mark.parametrize("changed", ["mtime and size", "mtime only", "size only"])
def test_a_zim_replaced_at_the_same_path_is_not_served_from_cache(
    home: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    """Nothing here clears a cache. The file at `first` is replaced by another ZIM with the same `Name` (and so the
    same library, a new uuid), and the only thing that can tell the caches is the stat of the path. A real
    replace-while-open is impossible on Windows (libzim holds the file), so the replacement is simulated where the
    library meets the file system: `Path.stat` for that path reports the new file, and opening it opens the new
    bytes. The `mtime only` / `size only` variants pin each half of the `(path, mtime, size)` key."""
    first = build_zim(home / "zim", extra={"extra": shell("<h1>One</h1><p>first body</p>")})
    second_page = "<h1>Two</h1>" + "".join(f"<p>second body line {n}</p>" for n in range(300))
    second = build_zim(home / "elsewhere", "second.zim", extra={"extra": shell(second_page)})
    old, new = first.stat(), second.stat()
    assert old.st_mtime_ns != new.st_mtime_ns and old.st_size != new.st_size, "the two files must differ"
    assert "first body" in service.read("acme§extra")["content"]

    swapped = {"on": False}
    real_stat, reader = Path.stat, _libzim.load("reader")
    real_archive = reader.Archive

    def stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if swapped["on"] and self == first:
            return SimpleNamespace(
                st_mode=old.st_mode,
                st_mtime_ns=old.st_mtime_ns if changed == "size only" else new.st_mtime_ns,
                st_size=old.st_size if changed == "mtime only" else new.st_size,
            )
        return real_stat(self, *args, **kwargs)

    def archive(path: str) -> Any:
        return real_archive(str(second) if swapped["on"] and path == str(first) else path)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(reader, "Archive", archive)
    swapped["on"] = True
    after = service.read("acme§extra")["content"]
    assert "second body line 299" in after and "first body" not in after
    swapped["on"] = False  # let the fixture's teardown release both handles through the real file system


def test_a_question_with_a_word_no_page_contains_still_finds_pages_and_marks_them_partial(acme: Path) -> None:
    """libzim's parser needs every term: 'automated' occurs nowhere, so the strict query is empty. Found live on
    DevDocs Flask ('write automated tests for a flask application' matched nothing)."""
    result = service.search("how do the automated gaskets and sprockets work", "acme")
    assert result["hits"], "a missing word must not erase the whole answer"
    assert result["hits"][0]["match"] == "some terms"
    assert result["hits"][0]["ref"] == f"{BOOK}§guide/config", "the rare words (gaskets, sprockets) decide"
    strict = service.search("gaskets sprockets", "acme")
    assert strict["hits"][0]["match"] == "full-text", "when every word is present the match is not marked partial"


# --- section-level hits and excerpt chrome ----------------------------------------------------------------------


def _single_page_library(home: Path) -> None:
    service.forget()
    build_zim(home / "zim", extra={"manual": zimfixture.BIG_MANUAL, "man1/frobnicate.1": zimfixture.MAN_PAGE})


def test_a_large_article_hit_names_the_best_section_and_excerpts_from_it(home: Path) -> None:
    _single_page_library(home)
    book = library.find("acme", library.scan())
    doc, _, _ = service.document(book, "manual")
    assert len(doc.blocks) > service.LARGE_ARTICLE_BLOCKS, "the fixture must be over the threshold"
    hit = service.search("prime the flux capacitor before the gizmo spins", "acme")["hits"][0]
    assert hit["ref"] == f"{BOOK}§manual", "ref still names the article, so existing consumers do not break"
    assert hit["section"]["ref"] == f"{BOOK}§manual#flux-capacitor"
    assert hit["section"]["anchor"] == "flux-capacitor" and hit["section"]["heading"] == "Flux capacitor"
    assert "primed before the gizmo spins" in hit["excerpt"]
    assert "cite" not in hit["section"], "zim_cite builds it from the section ref"
    assert service.cite(hit["section"]["ref"])["cite"].endswith("entry manual#flux-capacitor")
    read = service.read(hit["section"]["ref"])
    assert read["scope"] == "section" and "primed before" in read["content"], "the section ref is readable"


def test_section_choice_finds_a_definition_and_a_rare_word_in_a_body(home: Path) -> None:
    _single_page_library(home)
    spin = service.search("gizmo.spin rate", "acme")["hits"][0]
    assert spin["section"]["ref"] == f"{BOOK}§manual#gizmo.spin" and spin["section"]["blocks"] <= 2
    body = service.search("zorblax regulator", "acme")["hits"][0]
    assert body["section"]["anchor"] == "calibration", "a word only in a section's body still picks that section"
    deep = service.search("quibbleframe", "acme")["hits"][0]
    assert deep["section"]["anchor"] == "gizmo.halt", "the child definition beats the section that contains it"


def test_the_excerpt_comes_from_inside_the_chosen_section(home: Path) -> None:
    _single_page_library(home)
    hit = service.search("gadget storage sentence", "acme")["hits"][0]
    assert hit["section"]["anchor"] == "storage"
    assert hit["excerpt"].startswith("storage filler"), "not the better-scoring block earlier on the page"


def test_a_small_article_hit_has_no_section_and_the_same_excerpt(acme: Path) -> None:
    hit = service.search("timeout flange spin", "acme")["hits"][0]
    assert "section" not in hit and hit["ref"] == f"{BOOK}§guide/config"
    assert "timeout setting bounds" in hit["excerpt"]


def test_excerpts_skip_page_chrome_and_read_preformatted_sections(home: Path) -> None:
    _single_page_library(home)
    hit = service.search("frobnicate knob latch", "acme")["hits"][0]
    assert hit["ref"] == f"{BOOK}§man1/frobnicate.1" and "section" not in hit
    assert "Pages that refer" not in hit["excerpt"] and "example.org" not in hit["excerpt"]
    assert "rotates the knob" in hit["excerpt"], "preformatted sections are excerpted when no prose matches"


def test_chrome_blocks_are_recognised() -> None:
    chrome = [
        "Pages that refer to this page: [a(1)](man1/a.1), b(2)",
        "---",
        "... [https://example.org/x](https://example.org/x)",
        "https://example.org/x",
    ]
    assert all(service._is_chrome(block) for block in chrome)
    prose = ["Use https://example.org/x to fetch it.", "See the pages that refer to this page.", "A real sentence."]
    assert [service._is_chrome(block) for block in prose] == [False, False, False]


# --- entries that are not documentation, translations, header chrome -------------------------------------------


def _crawl_library(home: Path) -> None:
    service.forget()
    build_zim(
        home / "zim",
        extra={
            "disqus.com/embed/comments/": zimfixture.EMBED_FRAME,
            "accounts.google.com/o/oauth2/iframe": zimfixture.EMBED_FRAME,
            "notdisqus.com/page": zimfixture.EMBED_FRAME,
            "links.disqus.com/frame": zimfixture.EMBED_FRAME,
        },
    )


def test_third_party_frames_are_neither_listed_as_articles_nor_returned_as_hits(home: Path) -> None:
    """devhints.io_en_all: 690 of 1,037 HTML entries were `disqus.com/...` frames, one more an OAuth frame."""
    _crawl_library(home)
    listed = [e["ref"].split("§")[1] for e in service.outline("acme", limit=100)["entries"]]
    assert "disqus.com/embed/comments/" not in listed and "accounts.google.com/o/oauth2/iframe" not in listed
    assert "links.disqus.com/frame" not in listed, "a subdomain of a frame host is a frame host"
    assert "notdisqus.com/page" in listed, "only the host itself or a subdomain of it is a frame host"
    found = [h["ref"].split("§")[1] for h in service.search("gaskets sprockets widget", "acme")["hits"]]
    assert "notdisqus.com/page" in found and not any(p.startswith(("disqus.com", "accounts.google")) for p in found)


def _translated_library(home: Path) -> None:
    service.forget()
    build_zim(home / "zim", extra={"tr/gasket": zimfixture.GASKET_EN, "tr/gasket_(Deutsch)": zimfixture.GASKET_DE})


def test_translations_rank_after_the_page_in_the_librarys_language(home: Path) -> None:
    """archlinux_en_all: `_(Español)`-style copies crowded the English page out of the top 5."""
    _translated_library(home)
    engine = [h["ref"].split("§")[1] for h in service.search("gaskets sprockets", "acme", language="any")["hits"]]
    assert engine.index("tr/gasket_(Deutsch)") < engine.index("tr/gasket"), "precondition: the engine prefers it"
    hits = service.search("gaskets sprockets", "acme")["hits"]
    order = [h["ref"].split("§")[1] for h in hits]
    assert order.index("tr/gasket") < order.index("tr/gasket_(Deutsch)"), "the base-language page comes first"
    german = hits[order.index("tr/gasket_(Deutsch)")]
    assert german["language"] == "de" and "language" not in hits[order.index("tr/gasket")]


def test_a_language_code_keeps_only_pages_in_that_language(home: Path) -> None:
    _translated_library(home)
    only = [h["ref"].split("§")[1] for h in service.search("gaskets sprockets", "acme", language="de")["hits"]]
    assert only == ["tr/gasket_(Deutsch)"]
    english = [h["ref"].split("§")[1] for h in service.search("gaskets sprockets", "acme", language="EN-gb")["hits"]]
    assert "tr/gasket" in english and "tr/gasket_(Deutsch)" not in english


def test_language_matching_accepts_iso_639_3_against_the_two_letter_code() -> None:
    assert service._same_language("en", "eng") and service._same_language("en-GB", "en")
    assert not service._same_language("de", "eng") and not service._same_language("ru", "en")


def test_a_metadata_header_is_not_the_search_excerpt(home: Path) -> None:
    """peps.python_en_all: the excerpt of PEP 649, 669 and 728 was the line 'Discourse thread'."""
    service.forget()
    build_zim(home / "zim", extra={"pep-9999": zimfixture.PEP_LIKE})
    hit = next(h for h in service.search("discourse quillfeather", "acme")["hits"] if h["ref"].endswith("pep-9999"))
    assert hit["excerpt"] == "This PEP describes how a quillfeather is trimmed."


def test_a_field_list_without_a_closing_rule_is_prose_not_a_header() -> None:
    blocks = ["**Note:**", "Mind the gap.", "**Warning:**", "Mind it again."]
    assert service._header_end(blocks) == 0
    assert service._header_end(["**Author:**", "A", "**Status:**", "Final", "---", "Body"]) == 5
    assert service._header_end(["**Author:**", "A", "---", "Body"]) == 0, "one label is not a header"


def test_a_section_needs_at_least_two_of_the_querys_words(home: Path) -> None:
    """Found live: 'create a directory with missing parents' attached the Rust std index section about the
    'library/std/ directory', one stray word in an unrelated part of the page."""
    _single_page_library(home)
    stray = service.search("zorblax mumbleglorp", "acme")["hits"]
    assert stray and all("section" not in h for h in stray), "one matching word in a section is not an answer"
    strong = service.search("calibrate zorblax regulator", "acme")["hits"][0]
    assert strong["section"]["anchor"] == "calibration"


def test_the_library_listing_is_lean_bounded_and_says_what_it_left_out(home: Path) -> None:
    for name in ("one", "two", "three"):
        build_zim(home / "zim", f"{name}.zim", name=f"lib_en_{name}", title=name.title(), date="2026-10-01")
    full = service.libraries()
    assert (full["total"], full["truncated"], len(full["libraries"])) == (3, False, 3)
    cut = service.libraries(limit=2)
    assert (cut["total"], cut["truncated"], len(cut["libraries"])) == (3, True, 2)
    assert len(service.libraries("two", limit=1)["libraries"]) == 1
    lean, rich = full["libraries"][0], service.libraries(verbose=True)["libraries"][0]
    assert {"description", "creator", "tags", "license"}.isdisjoint(lean)
    assert {"description", "creator", "tags", "license", "provenance"} <= set(rich)
    assert len(json.dumps(lean)) < len(json.dumps(rich)), "the lean row is the smaller one"
    with pytest.raises(ZimloreError, match="limit must be"):
        service.libraries(limit=0)
    assert service.libraries(limit=5000)["clamped"] == {"limit": 1000}, "a huge limit is clamped and says so"


def test_the_outline_is_cut_to_a_token_budget_and_resumes_without_loss(acme: Path) -> None:
    whole = service.outline("acme§guide/config", max_tokens=50_000)
    assert whole["truncated"] is False and "next" not in whole
    seen: list[dict[str, object]] = []
    start = 0
    for _ in range(40):
        page = service.outline("acme§guide/config", start=start, max_tokens=60)
        assert page["outline"], "a page always carries at least one row"
        seen += page["outline"]
        if "next" not in page:
            break
        assert page["truncated"] is True
        start = page["next"]["start"]
    assert seen == whole["outline"], "paging by budget neither skips nor repeats rows"
    library_whole = service.outline("acme", max_tokens=50_000)["entries"]
    paged: list[dict[str, object]] = []
    start = 0
    for _ in range(40):
        page = service.outline("acme", start=start, max_tokens=40)
        paged += page["entries"]
        if "next" not in page:
            break
        start = page["next"]["start"]
    assert paged == library_whole


def test_an_entry_with_no_close_match_gives_no_empty_did_you_mean(acme: Path) -> None:
    with pytest.raises(ZimloreError) as caught:
        service.read("acme§qqqqqqqq/zzzzzz")
    assert "did_you_mean" not in caught.value.extra, "an empty list is noise to an agent"


def test_a_one_word_query_gets_a_section_only_when_the_word_is_distinctive_or_in_the_heading(home: Path) -> None:
    """Found on the cryptography docs: 'x509' attached 'Custom PKCS7 Test Vectors' (a body mention among dozens),
    while 'quibbleframe', in one definition's body, is rightly answered by that definition."""
    build_zim(
        home / "zim",
        extra={
            "common": shell(
                "<h1>Common</h1>"
                + "".join(
                    f"<section id='s{n}'><h2>Part {n}</h2>"
                    f"<p>widget text number {n}.</p>{zimfixture._filler(f's{n}', 30)}</section>"
                    for n in range(8)
                ),
                "Common",
            )
        },
    )
    book = library.find("acme", library.scan())
    doc, _, _ = service.document(book, "common")
    assert len(doc.blocks) > service.LARGE_ARTICLE_BLOCKS, "the fixture must be a large article"
    hit = next(h for h in service.search("widget", "acme", limit=20)["hits"] if h["ref"].endswith("§common"))
    assert "section" not in hit, "a word in every section of the page is not distinctive"


def test_cite_states_freshness_without_the_constant(acme: Path) -> None:
    fresh = service.cite("acme§guide/config")["freshness"]
    assert set(fresh) == {"date", "age_days", "stale"}, "stale_after_days is stated once, in the server instructions"
