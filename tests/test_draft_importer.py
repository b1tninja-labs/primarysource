"""The importer behind an injected transport: spacing, pins, hostile responses, and what lands on disk."""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest
from draft_fixture import HOSTILE_XML, NAME, Clock, DraftSpec, FakeIetf, build_txt, sha, timed, v2_xml, v3_xml

from primarysource.draft import datatracker, importer, net
from primarysource.draft.net import Fetcher, Response
from primarysource.draft.store import Store
from primarysource.errors import LibError

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def make(*specs: DraftSpec) -> tuple[FakeIetf, Fetcher, Clock, list[float]]:
    fake = FakeIetf(*specs)
    clock = Clock()
    stamps: list[float] = []
    fetcher = Fetcher(timed(fake, clock, stamps), clock=clock.clock, sleep=clock.sleep)
    return fake, fetcher, clock, stamps


def test_an_import_stores_the_latest_revision_and_makes_five_requests_a_second_apart(tmp_path: Path) -> None:
    spec = DraftSpec(xml={"03": v2_xml()})
    fake, fetcher, clock, stamps = make(spec)
    report = importer.import_draft(NAME, fetcher=fetcher, store=Store(tmp_path), now=NOW)
    assert (report.rev, report.new, report.requests, report.xml_state) == ("03", True, 5, "v2")
    assert [u.rsplit("/", 1)[-1].split("?")[0] for u in fake.calls[:1]] == ["doc.json"]
    assert fake.calls[1:3] == [datatracker.replaced_by_url(NAME), datatracker.became_rfc_url(NAME)]
    assert fake.calls[3:] == [
        f"https://www.ietf.org/archive/id/{NAME}-03.txt",
        f"https://www.ietf.org/archive/id/{NAME}-03.xml",
    ]
    gaps = [b - a for a, b in zip(stamps, stamps[1:], strict=False)]
    assert all(gap >= 1.0 for gap in gaps), gaps
    assert clock.sleeps == [1.0] * 4  # the request itself takes 0.1 s; the rest of the second is waited out
    folder = tmp_path / NAME / "03"
    assert sorted(p.name for p in folder.iterdir()) == ["draft.txt", "draft.xml", "meta.json", "sections.json"]
    assert (folder / "draft.txt").read_bytes() == spec.text_for("03")
    assert not [p for p in (tmp_path / NAME).iterdir() if p.name.startswith(".")]


def test_a_digest_recorded_on_first_use_is_what_the_stored_revision_reports(tmp_path: Path) -> None:
    spec = DraftSpec()
    _, fetcher, _, _ = make(spec)
    store = Store(tmp_path)
    report = importer.import_draft(NAME, "02", fetcher=fetcher, store=store, now=NOW)
    meta = store.meta(NAME, "02")
    assert meta.txt_sha256 == report.txt_sha256 == sha(spec.text_for("02"))
    assert (meta.published, meta.authors, meta.title) == ("2026-03-03", ("Alice Example", "Bob Sample"), spec.title)
    assert report.pinned is False
    assert store.status(NAME) is not None


def test_an_explicit_digest_that_does_not_match_stores_nothing(tmp_path: Path) -> None:
    _, fetcher, _, _ = make(DraftSpec())
    store = Store(tmp_path)
    with pytest.raises(LibError, match="nothing was stored"):
        importer.import_draft(NAME, "03", fetcher=fetcher, store=store, expected_sha256="0" * 64, now=NOW)
    assert store.revisions(NAME) == []
    assert not (tmp_path / NAME / "03").exists()
    good = sha(DraftSpec().text_for("03"))
    assert importer.import_draft(
        NAME, "03", fetcher=make(DraftSpec())[1], store=store, expected_sha256=good, now=NOW
    ).pinned


def test_a_catalogue_pin_is_enforced_for_both_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from primarysource.draft import catalogue

    spec = DraftSpec(xml={"03": v2_xml()})
    txt = spec.text_for("03")
    pins = {
        NAME: catalogue.Tracked(
            NAME, "w", (), "03", "Active", (), None, "", "", {"03": catalogue.Pin(sha(txt), "f" * 64)}
        )
    }
    monkeypatch.setattr(catalogue, "TRACKED", pins)
    store = Store(tmp_path)
    with pytest.raises(LibError, match=r"\.xml has sha256"):
        importer.import_draft(NAME, fetcher=make(spec)[1], store=store, now=NOW)
    assert store.revisions(NAME) == []
    pins[NAME].pins["03"] = catalogue.Pin(sha(txt), sha(v2_xml()))
    assert importer.import_draft(NAME, fetcher=make(spec)[1], store=store, now=NOW).pinned
    spec.txt["03"] = txt + b"\nchanged\n"
    other = Store(tmp_path / "second")
    with pytest.raises(LibError, match=r"\.txt has sha256"):
        importer.import_draft(NAME, fetcher=make(spec)[1], store=other, now=NOW)


def test_a_stored_revision_is_not_fetched_again_and_never_overwritten(tmp_path: Path) -> None:
    spec = DraftSpec()
    store = Store(tmp_path)
    importer.import_draft(NAME, fetcher=make(spec)[1], store=store, now=NOW)
    fake, fetcher, _, _ = make(spec)
    spec.txt["03"] = b"different bytes\n"
    again = importer.import_draft(NAME, fetcher=fetcher, store=store, now=NOW)
    assert (again.new, again.requests) == (False, 3)  # only the status was refreshed
    assert not any(u.endswith(".txt") for u in fake.calls)
    assert (tmp_path / NAME / "03" / "draft.txt").read_bytes() != b"different bytes\n"
    with pytest.raises(LibError, match="already stored"):
        store.install(store.meta(NAME, "03"), b"x", None, store.segmented(NAME, "03"))


def test_an_older_revision_can_be_imported_beside_the_latest(tmp_path: Path) -> None:
    store = Store(tmp_path)
    spec = DraftSpec()
    importer.import_draft(NAME, "01", fetcher=make(spec)[1], store=store, now=NOW)
    importer.import_draft(NAME, fetcher=make(spec)[1], store=store, now=NOW)
    assert store.revisions(NAME) == ["01", "03"]
    assert store.resolve(NAME, None) == ("03", True)
    assert store.resolve(NAME, "01") == ("01", False)
    with pytest.raises(LibError, match="not stored") as caught:
        store.resolve(NAME, "02")
    assert caught.value.hint == f"primarysource draft import {NAME}-02"


def test_a_revision_the_datatracker_does_not_list_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no revision 09"):
        importer.import_draft(NAME, "09", fetcher=make(DraftSpec())[1], store=Store(tmp_path), now=NOW)


def test_an_unknown_draft_is_a_not_found_error_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="has no draft named draft-nobody-nothing"):
        importer.import_draft("draft-nobody-nothing", fetcher=make(DraftSpec())[1], store=Store(tmp_path), now=NOW)


def test_the_xml_is_optional_and_a_hostile_one_is_recorded_but_not_stored(tmp_path: Path) -> None:
    absent = importer.import_draft(NAME, fetcher=make(DraftSpec())[1], store=Store(tmp_path / "a"), now=NOW)
    assert (absent.xml_state, absent.xml_sha256) == ("absent", "")
    skipped = importer.import_draft(
        NAME, fetcher=make(DraftSpec())[1], store=Store(tmp_path / "b"), want_xml=False, now=NOW
    )
    assert (skipped.xml_state, skipped.requests) == ("skipped", 4)
    hostile = DraftSpec(xml={"03": HOSTILE_XML})
    refused = importer.import_draft(NAME, fetcher=make(hostile)[1], store=Store(tmp_path / "c"), now=NOW)
    assert refused.xml_state == "refused"
    assert not (tmp_path / "c" / NAME / "03" / "draft.xml").exists()
    v3 = importer.import_draft(
        NAME, fetcher=make(DraftSpec(xml={"03": v3_xml()}))[1], store=Store(tmp_path / "d"), now=NOW
    )
    assert v3.xml_state == "v3"


def test_a_missing_text_is_a_remedy_and_an_html_page_behind_a_200_is_not_a_draft(tmp_path: Path) -> None:
    spec = DraftSpec()
    fake, fetcher, _, _ = make(spec)
    url = f"https://www.ietf.org/archive/id/{NAME}-03.txt"
    fake.overrides[url] = [Response(404, b"<html/>", "text/html")]
    with pytest.raises(LibError, match="no text for") as caught:
        importer.import_draft(NAME, fetcher=fetcher, store=Store(tmp_path), now=NOW)
    assert "XML only" in caught.value.hint
    fake.overrides[url] = [Response(200, b"<html>soft 404</html>", "text/html; charset=utf-8")]
    with pytest.raises(LibError, match="not a text draft"):
        importer.import_draft(NAME, fetcher=fetcher, store=Store(tmp_path / "x"), now=NOW)
    fake.overrides[url] = [Response(200, b"   \n", "text/plain")]
    with pytest.raises(LibError, match="empty"):
        importer.import_draft(NAME, fetcher=fetcher, store=Store(tmp_path / "y"), now=NOW)
    assert Store(tmp_path / "y").revisions(NAME) == []


def test_text_that_is_not_text_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    for body, why in ((b"abc\x00def", "NUL"), (b"x" * 5000, "characters")):
        fake, fetcher, _, _ = make(DraftSpec())
        fake.overrides[f"https://www.ietf.org/archive/id/{NAME}-03.txt"] = [Response(200, body, "text/plain")]
        store = Store(tmp_path / f"case-{len(why)}")
        with pytest.raises(LibError, match=why):
            importer.import_draft(NAME, fetcher=fetcher, store=store, now=NOW)
        assert store.revisions(NAME) == []


@pytest.mark.parametrize(
    ("spec", "level"),
    [
        (DraftSpec(state="Expired", expires="2014-01-16 00:00:00"), "expired"),
        (DraftSpec(state="Replaced", replaced_by=("draft-example-frob-proto-ng",)), "replaced"),
        (DraftSpec(state="RFC", became_rfc=9999), "rfc"),
    ],
)
def test_the_status_snapshot_records_death_and_succession(tmp_path: Path, spec: DraftSpec, level: str) -> None:
    from primarysource.draft.status import lifecycle

    report = importer.import_draft(NAME, fetcher=make(spec)[1], store=Store(tmp_path), now=NOW)
    stored = Store(tmp_path).status(NAME)
    assert stored == report.status
    assert lifecycle(stored).level == level
    assert stored.replaced_by == spec.replaced_by
    assert stored.became_rfc == (f"RFC{spec.became_rfc}" if spec.became_rfc else None)
    assert "@" not in stored.to_json()  # author names are kept, their email addresses are not


def test_refresh_needs_no_stored_revision_and_writes_only_the_status(tmp_path: Path) -> None:
    store = Store(tmp_path)
    status = importer.refresh(NAME, fetcher=make(DraftSpec())[1], store=store, now=NOW)
    assert status.rev == "03"
    assert store.revisions(NAME) == []
    assert sorted(p.name for p in (tmp_path / NAME).iterdir()) == ["status.json"]


def test_a_read_only_library_refuses_to_fetch_or_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_READONLY", "1")
    fake, fetcher, _, _ = make(DraftSpec())
    with pytest.raises(LibError, match="read-only"):
        importer.import_draft(NAME, fetcher=fetcher, store=Store(tmp_path), now=NOW)
    with pytest.raises(LibError, match="read-only"):
        importer.refresh(NAME, fetcher=fetcher, store=Store(tmp_path), now=NOW)
    assert fake.calls == []


def test_a_busy_server_is_retried_after_its_retry_after_and_then_given_up_on(tmp_path: Path) -> None:
    fake, fetcher, clock, _ = make(DraftSpec())
    url = datatracker.doc_url(NAME)
    fake.overrides[url] = [Response(429, b"", "", 7.0)]
    assert importer.refresh(NAME, fetcher=fetcher, store=Store(tmp_path), now=NOW).rev == "03"
    assert 7.0 in clock.sleeps
    fake.overrides[url] = [Response(503, b"", "")] * 3
    with pytest.raises(LibError, match="answered 503") as caught:
        importer.refresh(NAME, fetcher=fetcher, store=Store(tmp_path / "other"), now=NOW)
    assert caught.value.hint == "try again later"


def test_the_datatracker_is_data_not_instructions(tmp_path: Path) -> None:
    def answer(body: object, status: int = 200) -> FakeIetf:
        fake = FakeIetf(DraftSpec())
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        fake.overrides[datatracker.doc_url(NAME)] = [Response(status, payload, "application/json")]
        return fake

    def run(fake: FakeIetf) -> None:
        clock = Clock()
        importer.refresh(
            NAME, fetcher=Fetcher(fake, clock=clock.clock, sleep=clock.sleep), store=Store(tmp_path), now=NOW
        )

    good = FakeIetf(DraftSpec())._doc(DraftSpec())  # noqa: SLF001
    for broken, message in (
        ({**good, "name": "draft-someone-else"}, "answered for"),
        ({**good, "rev": "9"}, "not a revision"),
        ({**good, "rev_history": "no"}, "not a list"),
        ({**good, "state": 7}, "not text"),
        ([1, 2], "not a JSON object"),
        (b"<html>not json", "not JSON"),
    ):
        with pytest.raises(LibError, match=message):
            run(answer(broken))
    assert Store(tmp_path).status(NAME) is None
    fat = {**good, "title": "t" * 10_000, "authors": [{"name": "n" * 1000}] * 500}
    run(answer(fat))
    status = Store(tmp_path).status(NAME)
    assert status is not None
    assert len(status.title) <= 500 and len(status.authors) <= 50 and len(status.authors[0]) <= 100


def test_relationship_answers_only_yield_names_that_match_the_grammar(tmp_path: Path) -> None:
    fake = FakeIetf(DraftSpec())
    evil = {
        "objects": [
            {"source": "/api/v1/doc/document/../../etc/passwd/"},
            {"source": "/api/v1/doc/document/draft-ok-one/"},
            {"source": 5},
        ]
    }
    fake.overrides[datatracker.replaced_by_url(NAME)] = [Response(200, json.dumps(evil).encode(), "application/json")]
    clock = Clock()
    status = importer.refresh(
        NAME, fetcher=Fetcher(fake, clock=clock.clock, sleep=clock.sleep), store=Store(tmp_path), now=NOW
    )
    assert status.replaced_by == ("draft-ok-one",)


def test_only_https_on_the_two_ietf_hosts_is_ever_requested() -> None:
    net.check_url("https://www.ietf.org/archive/id/draft-x-y-00.txt")
    net.check_url("https://datatracker.ietf.org/doc/draft-x-y/doc.json")
    for bad in (
        "http://www.ietf.org/archive/id/x.txt",
        "https://evil.example/archive/id/x.txt",
        "https://www.ietf.org.evil.example/x",
        "https://www.ietf.org@evil.example/x",
        "https://user:pw@www.ietf.org/x",
        "file:///etc/passwd",
        "ftp://www.ietf.org/x",
    ):
        with pytest.raises(LibError, match="refusing to fetch"):
            net.check_url(bad)
    with pytest.raises(LibError):
        Fetcher(lambda url: Response(200, b""), sleep=lambda s: None).get("https://evil.example/")


def test_a_redirect_off_the_allowed_hosts_is_refused() -> None:
    handler = net._Redirects()  # noqa: SLF001
    request = urllib.request.Request("https://www.ietf.org/archive/id/x.txt")
    with pytest.raises(LibError, match="refusing to fetch"):
        handler.redirect_request(request, None, 302, "Found", {}, "https://evil.example/x.txt")


def test_a_request_names_a_validated_draft_and_nothing_else() -> None:
    with pytest.raises(LibError):
        datatracker.doc_url("draft-x/../../admin")
    with pytest.raises(ValueError):
        datatracker.archive_url("draft-x-y", "00", "exe")
    assert datatracker.html_url("draft-x-y", "03") == "https://datatracker.ietf.org/doc/html/draft-x-y-03"


def test_the_fixture_text_survives_a_round_trip_through_the_store(tmp_path: Path) -> None:
    store = Store(tmp_path)
    importer.import_draft(NAME, fetcher=make(DraftSpec())[1], store=store, now=NOW)
    assert store.raw_text(NAME, "03").decode() == build_txt(NAME, "03")
    (tmp_path / NAME / "03" / "sections.json").write_text("{damaged", encoding="utf-8")
    assert [s.id for s in store.segmented(NAME, "03").sections][:3] == [
        "abstract",
        "status-of-this-memo",
        "copyright-notice",
    ]
    assert json.loads((tmp_path / NAME / "03" / "sections.json").read_text(encoding="utf-8"))["parser"]  # rebuilt
