"""The importer behind an injected transport: politeness, provenance, refusals. Nothing touches the network."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from iana_fixture import NAME, FakeIana, widgets

from primarysource.errors import LibError
from primarysource.iana import catalogue, importer
from primarysource.iana.importer import Response, import_registries, urllib_transport


@pytest.fixture(autouse=True)
def _writable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Another test's `--read-only` leaves PRIMARYSOURCE_READONLY in os.environ; these tests need it unset."""
    monkeypatch.delenv("PRIMARYSOURCE_READONLY", raising=False)


class Clock:
    """A fake clock whose sleep advances it, so the rate limit can be measured without waiting."""

    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_a_fetch_stores_the_bytes_exactly_with_sha256_and_updated_date(tmp_path: Path) -> None:
    fake = FakeIana({NAME: widgets()})
    report = import_registries([NAME], base=tmp_path, transport=fake)
    assert (tmp_path / f"{NAME}.xml").read_bytes() == widgets()
    (outcome,) = report.outcomes
    assert outcome.status == "fetched" and outcome.updated == "2031-02-03"
    record = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["files"][NAME]
    assert record["sha256"] == hashlib.sha256(widgets()).hexdigest() == outcome.sha256
    assert record["updated"] == "2031-02-03" and record["size"] == len(widgets())
    assert record["url"] == f"https://www.iana.org/assignments/{NAME}/{NAME}.xml"
    assert record["last_modified"] == fake.last_modified and record["fetched"]


def test_every_request_names_a_user_agent_and_a_second_visit_is_conditional(tmp_path: Path) -> None:
    fake = FakeIana({NAME: widgets()})
    import_registries([NAME], base=tmp_path, transport=fake)
    again = import_registries([NAME], base=tmp_path, transport=fake)
    assert all(headers["User-Agent"].startswith("primarysource-iana/") for _, headers in fake.requests)
    assert "If-Modified-Since" not in fake.requests[0][1]
    assert fake.requests[1][1]["If-Modified-Since"] == fake.last_modified
    assert again.outcomes[0].status == "unchanged" and again.outcomes[0].updated == "2031-02-03"
    forced = import_registries([NAME], base=tmp_path, transport=fake, force=True)
    assert "If-Modified-Since" not in fake.requests[2][1] and forced.outcomes[0].status == "identical"


def test_requests_are_spaced_at_least_one_second_apart(tmp_path: Path) -> None:
    names = ["demo-a", "demo-b", "demo-c"]
    fake = FakeIana({n: widgets(n) for n in names})
    clock = Clock()
    import_registries(names, base=tmp_path, transport=fake, clock=clock, sleep=clock.sleep)
    assert clock.sleeps == [1.0, 1.0]
    assert len(fake.requests) == 3


def test_an_interval_under_one_second_is_refused_before_any_request(tmp_path: Path) -> None:
    fake = FakeIana({NAME: widgets()})
    with pytest.raises(LibError, match="under 1 second"):
        import_registries([NAME], base=tmp_path, transport=fake, interval=0.2)
    assert fake.requests == []


@pytest.mark.parametrize("bad", ["../etc/passwd", "Dns-Parameters", "a/b", "", "x y", "..", "a..b"])
def test_a_bad_name_is_refused_before_the_first_request(tmp_path: Path, bad: str) -> None:
    fake = FakeIana({NAME: widgets()})
    with pytest.raises(LibError):
        import_registries([NAME, bad], base=tmp_path, transport=fake)
    assert fake.requests == []


def test_no_names_says_what_to_pass(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="no registry named") as caught:
        import_registries([], base=tmp_path, transport=FakeIana({}))
    assert "--all" in caught.value.hint


def test_a_404_stops_the_run_and_keeps_what_was_already_imported(tmp_path: Path) -> None:
    fake = FakeIana({"demo-a": widgets("demo-a")})
    with pytest.raises(LibError, match="HTTP 404"):
        import_registries(["demo-a", "demo-gone"], base=tmp_path, transport=fake, interval=1.0, sleep=lambda _: None)
    assert (tmp_path / "demo-a.xml").is_file() and not (tmp_path / "demo-gone.xml").exists()
    assert "demo-a" in json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["files"]


def test_a_file_whose_root_id_is_not_the_name_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    fake = FakeIana({"demo-a": widgets("demo-other")})
    with pytest.raises(LibError, match="not 'demo-a'"):
        import_registries(["demo-a"], base=tmp_path, transport=fake)
    assert not list(tmp_path.iterdir())


def test_hostile_xml_from_the_server_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    evil = b'<!DOCTYPE registry [<!ENTITY a "x">]><registry xmlns="http://www.iana.org/assignments" id="demo-a"/>'
    with pytest.raises(LibError, match="document type declarations"):
        import_registries(["demo-a"], base=tmp_path, transport=FakeIana({"demo-a": evil}))
    html = b"<!doctype html><html><body>Page not found</body></html>"
    with pytest.raises(LibError):
        import_registries(["demo-a"], base=tmp_path, transport=FakeIana({"demo-a": html}))
    assert not list(tmp_path.glob("*.xml"))


def test_an_oversize_body_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importer, "MAX_BYTES", 100)
    with pytest.raises(LibError, match="is over"):
        import_registries(["demo-a"], base=tmp_path, transport=FakeIana({"demo-a": widgets("demo-a")}))


def test_a_read_only_library_never_fetches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_READONLY", "1")
    fake = FakeIana({NAME: widgets()})
    with pytest.raises(LibError, match="read-only"):
        import_registries([NAME], base=tmp_path, transport=fake)
    assert fake.requests == []


def test_the_default_transport_refuses_any_url_outside_the_assignments_tree() -> None:
    for url in ("http://www.iana.org/assignments/x/x.xml", "https://example.com/assignments/x", "file:///etc/passwd"):
        with pytest.raises(LibError, match="refusing to fetch"):
            urllib_transport(url, {})


def test_the_home_is_primarysource_home_slash_iana(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    import_registries([NAME], transport=FakeIana({NAME: widgets()}))
    assert (tmp_path / "iana" / f"{NAME}.xml").is_file() and (tmp_path / "iana" / "manifest.json").is_file()


def test_the_catalogue_lists_dated_registries_with_the_layout_url_and_the_terms() -> None:
    names = [e.name for e in catalogue.ENTRIES]
    assert len(names) == len(set(names)) and {"dns-parameters", "bootp-dhcp-parameters", "bgp-parameters"} <= set(
        names
    )
    assert {"stun-parameters", "tls-parameters", "http-status-codes"} <= set(names)
    for entry in catalogue.ENTRIES:
        assert entry.url == f"https://www.iana.org/assignments/{entry.name}/{entry.name}.xml"
        assert len(entry.read) == 10 and entry.title
    assert catalogue.TERMS.licence == "CC0-1.0" and catalogue.TERMS.placement == "layer"
    assert catalogue.TERMS.terms_url == "https://www.iana.org/help/licensing-terms"


def test_a_response_is_a_plain_value() -> None:
    assert Response(200, {}, b"x").status == 200
