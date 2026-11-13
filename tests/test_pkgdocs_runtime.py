"""Import, refs, read, outline, search, cite and status over a synthesised one-tree collection."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest
from pkgdocs_fixture import (
    COMMIT,
    FILES,
    INCLUDE,
    OTHER,
    URL,
    installed_library,
    make_spec,
    make_tar,
    manifest_for,
    no_wait,
    opener_for,
)

from primarysource.errors import LibError
from primarysource.model import Unit, span_hash
from primarysource.pkgdocs import fetch, index, store
from primarysource.pkgdocs.model import Doc, Sec
from primarysource.pkgdocs.runtime import Build, Library, Pin


def footer(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{key}: "):
            return line[len(key) + 2 :]
    return ""


def test_an_import_installs_an_edition_and_reports_what_it_did(tmp_path: Path) -> None:
    digest = manifest_for(FILES, INCLUDE)
    library = Library(make_spec(digest), tmp_path / "home")
    [report] = library.import_edition(opener=opener_for({URL: make_tar(FILES)}), throttle=no_wait())
    assert (report.tree, report.commit, report.docs, report.pinned) == ("main", COMMIT, 2, True)
    assert report.files_sha256 == digest and report.skipped == {
        "link, directory or special file": 1,
        "not selected": 1,
    }
    root = tmp_path / "home" / "demo" / "main" / COMMIT
    record = json.loads((root / "edition.json").read_text(encoding="utf-8"))
    assert record["licence"]["spdx"] == "CC0-1.0" and record["files_sha256"] == digest and record["docs"] == 2
    assert [p.name for p in (tmp_path / "home" / "demo" / "main").iterdir()] == [COMMIT], "no staging left behind"
    status = library.status()
    assert "licence: CC0-1.0 (layer)" in status and f"v1 {COMMIT[:12]} 2026-01-01: imported" in status


def test_a_wrong_pin_installs_nothing_and_an_unpinned_edition_needs_consent(tmp_path: Path) -> None:
    opener = opener_for({URL: make_tar(FILES)})
    wrong = Library(make_spec("0" * 64), tmp_path / "home")
    with pytest.raises(LibError, match="not the .* pinned"):
        wrong.import_edition(opener=opener, throttle=no_wait())
    assert not (tmp_path / "home" / "demo" / "main").exists() or not any(
        (tmp_path / "home" / "demo" / "main").iterdir()
    )
    unpinned = Library(make_spec(None), tmp_path / "home2")
    with pytest.raises(LibError, match="no recorded digest") as caught:
        unpinned.import_edition(opener=opener, throttle=no_wait())
    assert "--allow-unpinned" in caught.value.hint
    [report] = unpinned.import_edition(opener=opener, throttle=no_wait(), allow_unpinned=True)
    assert not report.pinned


def test_import_selects_trees_and_commits_and_reads_a_downloaded_archive(tmp_path: Path) -> None:
    library = Library(make_spec(manifest_for(FILES, INCLUDE)), tmp_path / "home")
    with pytest.raises(LibError, match="no tree named 'x'"):
        library.import_edition("x")
    with pytest.raises(LibError, match="not one pinned edition"):
        library.import_edition(commit="deadbeef", opener=opener_for({}))
    path = tmp_path / "local.tar.gz"
    path.write_bytes(make_tar(FILES))
    [report] = library.import_edition("main", "v1", str(path))
    assert report.commit == COMMIT
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(make_tar({**FILES, "docs/alpha.md": b"# changed\n"}))
    with pytest.raises(LibError, match="not the .* pinned"):
        library.import_edition("main", None, str(bad))


def test_a_build_that_repeats_a_document_id_is_refused(tmp_path: Path) -> None:
    spec = make_spec(None)
    tree = spec.trees[0]

    def twice(files: Mapping[str, bytes], pin: Pin) -> Build:
        doc = Doc(
            "same",
            "Same",
            Unit.BLOCK,
            (Sec("1", "S", 1, "s"),),
        )
        return Build((doc, doc))

    broken = replace(spec, trees=(replace(tree, build=twice),))
    with pytest.raises(LibError, match="duplicate document ids: same"):
        Library(broken, tmp_path).import_edition(
            opener=opener_for({URL: make_tar(FILES)}), throttle=no_wait(), allow_unpinned=True
        )


def test_a_section_is_found_by_id_anchor_title_or_a_unique_part_of_a_title(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    by_id = library.read("demo:alpha§1.1")
    assert "Text about gaskets and sprockets." in by_id
    assert library.read("alpha#first-part").splitlines()[0] == "## 1.1 First part"
    assert library.read("alpha§first PART:").splitlines()[0] == "## 1.1 First part"
    assert "repeated heading" not in library.read("alpha§1.1")
    assert library.read("alpha§Notes").startswith("### 1.2.1 Notes")
    repeated = library.read("alpha§First part")
    assert footer(repeated, "warning") == "2 sections are titled 'First part'; the first was read"


def test_an_ambiguous_or_unknown_section_is_an_error_that_lists_the_candidates(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    with pytest.raises(LibError, match="'part' matches 3 sections") as caught:
        library.read("alpha§part")
    assert "1.1 First part" in caught.value.hint and "1.2 Second part" in caught.value.hint
    with pytest.raises(LibError, match="no section 'Frist part'") as typo:
        library.read("alpha§Frist part")
    assert "First part" in typo.value.hint
    with pytest.raises(LibError, match="no document 'alfa'") as doc:
        library.read("alfa§1")
    assert "alpha" in doc.value.hint


def test_a_block_is_addressed_by_pilcrow_and_a_missing_one_is_an_error(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    second = library.read("demo:alpha§1.1¶2")
    assert second.startswith("Another paragraph on gaskets.\n\ncite: ")
    assert footer(second, "span") == span_hash("Another paragraph on gaskets.")
    assert footer(second, "cite").startswith(f"demo:alpha@{COMMIT[:12]}§1.1¶2 -- ")
    with pytest.raises(LibError, match="has 2 blocks; there is no ¶3"):
        library.read("alpha§1.1¶3")


def test_an_escaped_hash_in_a_title_a_collection_prefix_aliases_and_bare_numbers_resolve(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    assert "Hash in a title." in library.read("beta§C%23 notes")
    assert library.read("a§1.1") == library.read("alpha§1.1")
    assert library.read("demo:1.1") == library.read("alpha§1.1"), "a bare section number finds its document by alias"
    assert library.read("DEMO:alpha§1.1") == library.read("alpha§1.1")
    with pytest.raises(LibError, match="not a ref"):
        library.read("???")
    with pytest.raises(LibError, match="line range is not a ref"):
        library.read("alpha:1-5")


def test_an_edition_is_chosen_by_commit_prefix_or_label(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    assert library.read(f"alpha@{COMMIT[:7]}§1.1") == library.read("alpha§1.1")
    assert library.read("alpha@v1§1.1") == library.read("alpha§1.1")
    with pytest.raises(LibError, match="no imported edition matches 'dead'"):
        library.read("alpha@dead§1.1")
    assert footer(library.read("1.1@aaaaaa"), "cite").startswith(f"demo:alpha@{COMMIT[:12]}§1.1")


def test_a_section_includes_its_subsections_and_paging_follows_next_without_loss(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    whole = library.read("alpha§1", max_tokens=5000)
    for text in ("# 1 Alpha", "## 1.1 First part", "### 1.2.1 Notes", "A repeated heading."):
        assert text in whole
    pieces: list[str] = []
    start = 1
    while True:
        page = library.read("alpha§1", start=start, max_tokens=8)
        pieces.append(page.split("\n\ncite:")[0])
        following = footer(page, "next")
        if not following:
            break
        start = int(following.removeprefix("start="))
    assert "\n\n".join(pieces) == whole.split("\n\ncite:")[0]
    assert len(pieces) > 3


def test_cite_gives_the_licence_the_source_file_and_the_span_hash_of_the_cited_text(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    text = library.cite("alpha§1.1")
    line = text.splitlines()[0]
    assert 'Alpha, "First part" §1.1' in line and "docs/alpha.md" in line and "licence CC0-1.0 (CC0)" in line
    assert f"commit {COMMIT[:12]}" in line
    expected = span_hash("Text about gaskets and sprockets.\n\nAnother paragraph on gaskets.")
    assert footer(text, "span") == expected
    assert library.cite("alpha§1.1¶1").endswith(f"span: {span_hash('Text about gaskets and sprockets.')}\n")


def test_outline_lists_sections_with_refs_and_pages(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    text = library.outline("alpha")
    assert text.splitlines()[0] == "Alpha"
    assert f"    1.2.1  Notes  [1]  demo:alpha@{COMMIT[:12]}§1.2.1" in text
    paged = library.outline("alpha", max_tokens=20)
    assert footer(paged, "next").startswith("start=")
    with pytest.raises(LibError, match="not a ref"):
        library.outline("")


def test_docs_lists_ids_and_titles_and_filters_by_prefix(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    assert library.docs().splitlines()[:2] == ["alpha  Alpha", "beta  Beta"]
    assert library.docs("be").splitlines()[0] == "beta  Beta"
    assert library.docs("zz").startswith("no documents with an id starting 'zz'")
    assert "next: start=2" in library.docs(limit=1)


def test_search_ranks_sections_sanitises_operators_and_relaxes_with_a_note(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    found = library.search("sprockets gaskets")
    first = found.splitlines()[0]
    assert first.startswith(f"demo:alpha@{COMMIT[:12]}§1.1: Alpha / First part -- ")
    assert "[sprockets]" in first and not footer(found, "relaxed")
    for hostile in ('"', "AND OR NOT", "NEAR(", "a*b", "col:val", "-x", "' OR 1=1 --"):
        library.search(hostile + " sprockets")  # must not raise
    relaxed = library.search("sprockets zebra")
    assert "§1.1" in relaxed and footer(relaxed, "relaxed")
    assert library.search("zebra").startswith("no sections matched")
    with pytest.raises(LibError, match="nothing to search for"):
        library.search("!!! ???")


def test_search_pages_filters_by_document_prefix_and_treats_like_wildcards_literally(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    everything = library.search("part notes sprockets intro", limit=2)
    assert footer(everything, "next") == "start=3"
    second = library.search("part notes sprockets intro", limit=2, start=3)
    assert second.splitlines()[0] not in everything
    assert "alpha" not in library.search("intro", doc_prefix="beta")
    assert library.search("intro", doc_prefix="%").startswith("no sections matched")
    assert library.search("intro", doc_prefix="_eta").startswith("no sections matched")


def test_nothing_imported_is_an_error_with_the_remedy_never_an_empty_result(tmp_path: Path) -> None:
    library = Library(make_spec(None), tmp_path / "empty")
    calls: list[Callable[[], str]] = [
        lambda: library.read("alpha§1"),
        lambda: library.docs(),
        lambda: library.search("x"),
    ]
    for call in calls:
        with pytest.raises(LibError, match="Demo documents is not imported") as caught:
            call()
        assert caught.value.hint == "primarysource demo import"
    assert "not imported" in library.status()


def test_the_default_home_follows_the_environment_and_a_reimport_replaces_the_edition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path / "env-home"))
    spec = make_spec(manifest_for(FILES, INCLUDE))
    library = Library(spec)
    library.import_edition(opener=opener_for({URL: make_tar(FILES)}), throttle=no_wait())
    assert (tmp_path / "env-home" / "demo" / "main" / COMMIT / "edition.json").is_file()
    library.import_edition(opener=opener_for({URL: make_tar(FILES)}), throttle=no_wait())
    assert [p.name for p in (tmp_path / "env-home" / "demo" / "main").iterdir()] == [COMMIT]


def test_a_damaged_edition_is_reported_by_the_one_asked_for_and_skipped_in_listings(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    root = tmp_path / "home" / "demo" / "main" / COMMIT
    (root / "index.json").write_text("not json", encoding="utf-8")
    assert store.installed(tmp_path / "home" / "demo" / "main") == []
    with pytest.raises(LibError, match="damaged"):
        store.Edition(root)
    with pytest.raises(LibError, match="is not imported"):
        library.read("alpha§1")


def test_an_unreadable_stored_document_is_a_liberror_with_the_remedy(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    root = tmp_path / "home" / "demo" / "main" / COMMIT
    (root / "docs" / "00001.json").write_text('{"id": "alpha"}', encoding="utf-8")
    with pytest.raises(LibError, match="damaged") as caught:
        library.read("alpha§1")
    assert caught.value.hint == "import the edition again"
    (root / "docs" / "00001.json").unlink()
    with pytest.raises(LibError, match="unreadable"):
        library.read("alpha§1")


def test_store_refuses_a_commit_that_is_not_hex_and_find_reports_ambiguity(tmp_path: Path) -> None:
    base = tmp_path / "b"
    with pytest.raises(LibError, match="not a commit id"):
        store.write_edition(base, "../evil", {}, [])
    doc = Doc("d", "D", Unit.BLOCK, (Sec("1", "S", 1, "s", ("x",)),))
    store.write_edition(base, "ab12" + "0" * 36, {"imported": "1"}, [doc])
    store.write_edition(base, "ab34" + "0" * 36, {"imported": "2"}, [doc])
    assert store.find(base, None, "demo", "h").commit.startswith("ab34")
    assert store.find(base, "ab12", "demo", "h").commit.startswith("ab12")
    with pytest.raises(LibError, match="matches more than one"):
        store.find(base, "ab", "demo", "h")
    with pytest.raises(LibError, match="no imported edition of demo"):
        store.find(base, "ff", "demo", "h")


def test_the_index_refuses_a_missing_file_and_a_different_schema(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no search index"):
        index.search(tmp_path / "gone.sqlite", "x")
    path = tmp_path / "i.sqlite"
    doc = Doc("d", "D", Unit.BLOCK, (Sec("1", "S", 1, "s", ("hello world",)),))
    assert index.build(path, [doc]) == 1
    hits, relaxed = index.search(path, "hello")
    assert [(h.doc, h.section) for h in hits] == [("d", "1")] and not relaxed
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(LibError, match="different schema version"):
        index.search(path, "hello")
    path.write_bytes(b"this is not a database" * 100)
    with pytest.raises(LibError, match="unreadable"):
        index.search(path, "hello")


def test_other_commits_are_listed_by_status_and_not_hidden(tmp_path: Path) -> None:
    library = installed_library(tmp_path)
    other = Library(make_spec(manifest_for(FILES, INCLUDE), commit=OTHER), tmp_path / "home")
    other.import_edition(opener=opener_for({URL: make_tar(FILES)}), throttle=no_wait())
    assert f"other imported commits: {COMMIT[:12]}" in other.status()
    assert fetch.manifest_digest({}) in {fetch.manifest_digest({})}
    assert library.read("alpha§1.1")
