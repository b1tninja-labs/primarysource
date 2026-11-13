"""Reading, outlining, searching, citing and `info` over a synthesised library."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cursor_check import follow_read
from draft_fixture import NAME, Clock, DraftSpec, FakeIetf, build_txt

from primarysource.draft import importer, views
from primarysource.draft.net import Fetcher
from primarysource.draft.store import Store
from primarysource.errors import LibError

NOW = datetime.now(UTC)
FAR = "2099-01-01 00:00:00"


def library(tmp_path: Path, *specs: DraftSpec, revs: tuple[str, ...] = (), when: datetime = NOW) -> Store:
    fake = FakeIetf(*specs)
    clock = Clock()
    fetcher = Fetcher(fake, clock=clock.clock, sleep=clock.sleep)
    store = Store(tmp_path)
    for spec in specs:
        for rev in revs or (None,):
            importer.import_draft(spec.name, rev, fetcher=fetcher, store=store, now=when)
    return store


def footer(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.rstrip("\n").split("\n\n")[-1].split("\n"):
        key, _, value = line.partition(": ")
        found[key] = value
    return found


@pytest.fixture
def alive(tmp_path: Path) -> Store:
    return library(tmp_path, DraftSpec(expires=FAR))


def test_a_ref_without_a_revision_reads_the_latest_stored_and_says_so(alive: Store) -> None:
    text = views.read(alive, f"{NAME}§1¶1")
    assert text.startswith("The Frobnicator Control Protocol moves invented gaskets")
    assert "no revision in the ref: read the latest stored revision -03" in footer(text)["warning"]
    named = views.read(alive, f"{NAME}-03§1¶1")
    assert "warning" not in footer(named)


def test_a_section_pages_by_paragraph_and_next_leads_to_the_rest(alive: Store) -> None:
    first = views.read(alive, f"{NAME}-03§2.1", max_tokens=1)
    assert footer(first)["next"] == f"{NAME}-03§2.1¶2"
    bodies, refs = follow_read(lambda ref: views.read(alive, ref, max_tokens=1), f"{NAME}-03§2.1")
    assert refs == [f"{NAME}-03§2.1", f"{NAME}-03§2.1¶2", f"{NAME}-03§2.1¶3"]
    pieces = [bodies[0].split("\n\n", 1)[1], *bodies[1:]]
    assert len(pieces) == 3
    assert "Messages are carried in frames." in pieces[0] and "+--------+" in pieces[1] and "flange once" in pieces[2]
    whole = views.read(alive, f"{NAME}-03§2.1")
    assert "next" not in footer(whole)
    assert footer(whole)["unit"] == "paragraph"
    assert footer(whole)["span"].startswith("sha256:")


def test_a_paragraph_is_cited_by_its_text_and_its_span_changes_when_it_does(alive: Store) -> None:
    first = views.read(alive, f"{NAME}-03§1¶2")
    assert first.splitlines()[0].startswith("A second paragraph says that every sprocket MUST")
    again = views.read(alive, f"{NAME}-03§1¶2")
    other = views.read(alive, f"{NAME}-03§1¶1")
    assert footer(first)["span"] == footer(again)["span"] != footer(other)["span"]


def test_the_overview_has_the_abstract_and_a_ref_for_every_section(alive: Store) -> None:
    text = views.read(alive, f"{NAME}-03")
    assert "Abstract" in text and "invented document specifies" in text
    assert f"{NAME}-03§2.1  2.1 Messages  (3)" in text
    assert f"{NAME}-03§A  Appendix A Worked Example  (1)" in text
    listed = [line for line in text.split("\n") if line.lstrip().startswith(f"{NAME}-03§")]
    outlined = views.outline(alive, f"{NAME}-03").split("\n")
    assert listed == [line for line in outlined if line.lstrip().startswith(f"{NAME}-03§")]


def test_the_outline_indents_by_depth_and_counts_paragraphs(alive: Store) -> None:
    lines = views.outline(alive, NAME).split("\n")
    assert f"{NAME}-03  Frobnicator Control Protocol" in lines
    assert f"  {NAME}-03§2.1  2.1 Messages  (3)" in lines
    assert f"{NAME}-03§security-considerations" not in "\n".join(lines)  # numbered 3 here, so its id is 3
    assert f"{NAME}-03§3  3 Security Considerations  (1)" in lines


def test_lines_of_the_text_are_read_as_the_file_has_them(alive: Store) -> None:
    expected = build_txt().replace("\f", "").split("\n")
    text = views.read(alive, f"{NAME}-03:41-42")
    assert text.split("\n\ncite:")[0] == "\n".join(expected[40:42]).rstrip("\n")
    assert ", lines 41-42." in footer(text)["cite"]
    with pytest.raises(LibError, match="past the end"):
        views.read(alive, f"{NAME}-03:99999-100000")


def test_the_cite_string_is_the_work_in_progress_form_with_a_section_anchor(alive: Store) -> None:
    cite = footer(views.cite(alive, f"{NAME}-03§2.1¶2"))["cite"]
    assert cite == (
        'A. Example and B. Sample, "Frobnicator Control Protocol", Work in Progress, Internet-Draft, '
        f"{NAME}-03, 3 April 2026, <https://datatracker.ietf.org/doc/html/{NAME}-03#section-2.1>, "
        "Section 2.1, paragraph 2."
    )
    appendix = footer(views.cite(alive, f"{NAME}-03§A"))["cite"]
    assert appendix.endswith("#section-appendix.a>, Appendix A.")
    unnumbered = footer(views.cite(alive, f"{NAME}-03§abstract"))["cite"]
    assert unnumbered.endswith(f'{NAME}-03>, "Abstract".')
    assert footer(views.cite(alive, f"{NAME}-03"))["cite"].endswith(f"{NAME}-03>.")


def test_a_section_that_is_not_there_says_what_is_close(alive: Store) -> None:
    with pytest.raises(LibError, match="has no section") as caught:
        views.read(alive, f"{NAME}-03§2.3")
    assert "2.1" in caught.value.hint or "2.2" in caught.value.hint
    with pytest.raises(LibError, match="has 3 paragraphs, not 9"):
        views.read(alive, f"{NAME}-03§2.1¶9")
    with pytest.raises(LibError, match="has no section"):
        views.cite(alive, f"{NAME}-03§77")
    with pytest.raises(LibError, match="not stored"):
        views.read(alive, "draft-not-here-00§1")
    for bad in ("", "RFC9000§1", "§1", "x" * 500, "draft-x-y-03§1¶0"):
        with pytest.raises(LibError):
            views.read(alive, bad)


def test_start_and_budget_are_checked(alive: Store) -> None:
    with pytest.raises(LibError):
        views.read(alive, f"{NAME}-03§2.1", max_tokens=0)
    with pytest.raises(LibError, match="has 3 paragraphs, not 9"):
        views.read(alive, f"{NAME}-03§2.1¶9")


@pytest.mark.parametrize(
    ("spec", "word"),
    [
        (DraftSpec(state="Expired", expires="2014-01-16 00:00:00"), "EXPIRED"),
        (DraftSpec(state="Replaced", replaced_by=("draft-example-frob-proto-ng",)), "REPLACED"),
        (DraftSpec(state="RFC", became_rfc=9999), "RFC"),
        (DraftSpec(state="Withdrawn by Submitter"), "WITHDRAWN"),
        (DraftSpec(expires="2020-01-01 00:00:00"), "EXPIRED"),
    ],
)
def test_a_dead_draft_says_so_before_the_text_and_after_it(tmp_path: Path, spec: DraftSpec, word: str) -> None:
    store = library(tmp_path, spec)
    for text in (
        views.read(store, f"{NAME}-03§1¶1"),
        views.read(store, f"{NAME}-03§1"),
        views.outline(store, NAME),
        views.cite(store, f"{NAME}-03§1"),
    ):
        assert text.startswith(f"[{word}"), text[:80]
        assert word in footer(text)["warning"]


def test_the_replacement_and_the_rfc_are_named(tmp_path: Path) -> None:
    replaced = library(tmp_path / "a", DraftSpec(state="Replaced", replaced_by=("draft-example-frob-proto-ng",)))
    assert "replaced by draft-example-frob-proto-ng" in views.read(replaced, f"{NAME}§1¶1")
    became = library(tmp_path / "b", DraftSpec(state="RFC", became_rfc=9999))
    assert "published as RFC9999: cite the RFC" in views.read(became, f"{NAME}§1¶1")
    assert "became: RFC9999" in views.info(became, NAME)


def test_an_older_revision_of_a_live_draft_is_flagged_as_not_the_latest(tmp_path: Path) -> None:
    store = library(tmp_path, DraftSpec(expires=FAR), revs=("01", "03"))
    old = views.read(store, f"{NAME}-01§1¶1")
    assert old.startswith("[-01 is not the latest revision: the datatracker listed -03]")
    assert "-01 is not the latest" in footer(old)["warning"]
    assert views.read(store, f"{NAME}-03§1¶1").startswith("The Frobnicator")
    assert views.read(store, f"{NAME}§1¶1").startswith("The Frobnicator")  # the latest stored is -03


def test_a_stale_status_asks_for_a_refresh(tmp_path: Path) -> None:
    store = library(tmp_path, DraftSpec(expires=FAR), when=NOW - timedelta(days=40))
    text = views.read(store, f"{NAME}-03§1¶1")
    assert "status was checked 40 days ago" in footer(text)["warning"]
    assert f"primarysource draft refresh {NAME}" in footer(text)["warning"]


def test_a_draft_with_no_stored_status_cannot_be_called_alive(alive: Store) -> None:
    (alive.root / NAME / "status.json").unlink()
    text = views.read(alive, f"{NAME}-03§1¶1")
    assert "expiry and replacement are unknown" in footer(text)["warning"]


def test_search_finds_sections_best_first_and_marks_dead_drafts(tmp_path: Path) -> None:
    live = DraftSpec(expires=FAR)
    dead = DraftSpec(
        name="draft-example-old-proto", state="Expired", expires="2014-01-01 00:00:00", title="Old Protocol"
    )
    store = library(tmp_path, live, dead)
    result = views.search(store, "retransmission timer")
    lines = result.split("\n\n")[0].split("\n")
    assert lines[0].startswith(f"{NAME}-03§2.2  2.2 Timers")
    assert any(line.startswith("draft-example-old-proto-03§2.2") and "[expired]" in line for line in lines)
    assert "not alive" in footer(result)["warning"]
    narrowed = views.search(store, "retransmission timer", name=NAME)
    assert "old-proto" not in narrowed
    assert "warning" not in footer(narrowed)


def test_search_relaxes_to_any_word_and_says_so(alive: Store) -> None:
    result = views.search(alive, "flange zebra")
    assert footer(result)["relaxed"].startswith("not every word matched")
    strict = views.search(alive, "flange gasket")
    assert "relaxed" not in footer(strict)
    assert views.search(alive, "zebra").startswith("no section matched")


def test_search_refuses_what_is_not_a_query(alive: Store, tmp_path: Path) -> None:
    for bad in ("", "   ", "!!! ???", "x" * 400):
        with pytest.raises(LibError):
            views.search(alive, bad)
    with pytest.raises(LibError, match="limit"):
        views.search(alive, "flange", limit=0)
    with pytest.raises(LibError, match="no draft is stored"):
        views.search(Store(tmp_path / "empty"), "flange")
    assert views.search(alive, 'flange" OR (gasket NEAR/3 sprocket) -x*').count("\n") >= 1  # operators are just words


def test_info_gives_the_standing_the_licence_legend_and_what_is_pinned(alive: Store) -> None:
    text = views.info(alive, NAME)
    for needle in (
        "datatracker state: Active",
        "standing: ACTIVE: active, expires 2099-01-01",
        "latest revision on the datatracker: -03",
        "revisions stored: -03",
        "pinned in the catalogue: no (trusted on first use)",
        "author's xml of -03: absent",
        "Trust Legal Provisions 5.0 §3.c applies",
        "RFC 2026 §2.2",
    ):
        assert needle in text, needle
    assert "warning" not in footer(text)


def test_info_on_a_dead_draft_puts_the_verdict_in_the_footer(tmp_path: Path) -> None:
    store = library(tmp_path, DraftSpec(state="Expired", expires="2014-01-16 00:00:00"))
    assert footer(views.info(store, NAME))["warning"].startswith("EXPIRED: expired on 2014-01-16")


def test_info_on_a_tracked_draft_not_yet_fetched_shows_the_catalogue_snapshot(tmp_path: Path) -> None:
    text = views.info(Store(tmp_path), "draft-ietf-sidrops-8210bis")
    assert "catalogue snapshot" in text and "primarysource draft refresh draft-ietf-sidrops-8210bis" in text
    assert "tracked for: rtrkit" in text
    with pytest.raises(LibError, match="neither stored nor tracked"):
        views.info(Store(tmp_path), "draft-nobody-nothing")


def test_list_shows_tracked_and_stored_drafts_with_state(alive: Store) -> None:
    text = views.list_tracked(alive)
    assert f"{NAME}  stored: -03  latest: -03  state: Active" in text
    assert "draft-ietf-sidrops-8210bis  stored: none" in text
    assert "(catalogue)" in text


def test_a_damaged_stored_revision_names_its_remedy(alive: Store) -> None:
    (alive.root / NAME / "03" / "meta.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(LibError, match="damaged") as caught:
        views.read(alive, f"{NAME}-03§1")
    assert "import that revision again" in caught.value.action
