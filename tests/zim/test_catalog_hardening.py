"""Redirects, caps, deadlines, replacement and hostile input in `catalog.py`, over the local server of
`test_catalog.py` (extended there with redirects, runaway and cut streams)."""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from primarysource.zim import catalog, manage
from primarysource.zim.errors import ZimloreError

from .test_catalog import FEED, NAME, _at, _publish, _serve, _zim_requests

Seen = list[tuple[str, str | None]]


def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    from primarysource.zim import cli

    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_redirect_to_a_non_local_plain_http_host_is_refused_for_the_feed_the_meta4_and_the_zim(
    tmp_path: Path,
) -> None:
    elsewhere = "http://127.0.0.2:9/final"
    served = tmp_path / "served"
    entry = _publish(served)
    with _serve(served, redirects={"/feed": elsewhere, f"/{NAME}.meta4": elsewhere}) as base:
        with pytest.raises(ZimloreError, match="only https"):
            catalog.query(base=f"{base}/feed")
        with pytest.raises(ZimloreError, match="only https"):
            catalog.download(_at(entry, base), tmp_path / "a")
    with (
        _serve(served, redirects={f"/{NAME}": elsewhere + ".zim"}) as base,
        pytest.raises(ZimloreError, match="only https"),
    ):
        catalog.download(_at(entry, base), tmp_path / "b")
    assert list((tmp_path / "b").glob("*.zim")) == [], "nothing was installed from the redirected host"


def test_a_redirect_that_stays_local_is_followed_and_still_verified(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    (served / "mirror").mkdir()
    (served / "mirror" / NAME).write_bytes((served / NAME).read_bytes())
    seen: Seen = []
    with _serve(served, redirects={f"/{NAME}": f"/mirror/{NAME}"}, log=seen) as base:
        got = catalog.download(_at(entry, base), tmp_path / "zim")
    assert got.read_bytes() == (served / NAME).read_bytes()
    assert [p for p, _ in seen if p.endswith(".zim")] == [f"/{NAME}", f"/mirror/{NAME}"]


def test_every_hop_is_checked_for_downgrades_and_non_public_addresses() -> None:
    kiwix = "https://download.kiwix.org/a"
    with pytest.raises(ZimloreError, match="https must stay https"):
        catalog._check_url("http://127.0.0.1/x", kiwix, origin_host="download.kiwix.org")
    for url in (
        "https://169.254.169.254/latest",
        "https://10.0.0.5/x",
        "https://[::1]/x",
        "https://127.1/x",
        "https://2130706433/x",
        "https://localhost/x",
        "https://printer.localhost/x",
    ):
        with pytest.raises(ZimloreError, match="loopback, private"):
            catalog._check_url(url, kiwix, origin_host="download.kiwix.org")
    catalog._check_url("https://lb.download.kiwix.org/x", kiwix, origin_host="download.kiwix.org")
    catalog._check_url("http://127.0.0.1:5/y", "http://127.0.0.1:4/x", origin_host="127.0.0.1")
    catalog._check_url("https://127.0.0.1/y", "http://127.0.0.1:4/x", origin_host="127.0.0.1")


def test_the_meta4_may_only_be_redirected_within_the_catalogue_domain() -> None:
    request = urllib.request.Request("https://download.kiwix.org/zim/a.zim.meta4")
    pinned = catalog._Redirects(pinned=True)
    inside = pinned.redirect_request(request, None, 302, "Found", {}, "https://lb.download.kiwix.org/zim/a.zim.meta4")
    assert inside is not None
    with pytest.raises(ZimloreError, match="must come from kiwix.org"):
        pinned.redirect_request(request, None, 302, "Found", {}, "https://mirror.example.org/a.zim.meta4")
    free = catalog._Redirects()
    assert free.redirect_request(request, None, 302, "Found", {}, "https://mirror.example.org/a.zim") is not None


def test_a_catalogue_entry_off_the_catalogue_domain_is_refused_before_any_fetch(tmp_path: Path) -> None:
    def never(_request: object) -> object:
        raise AssertionError("no request may be made")

    entry = catalog.CatalogEntry("x", "x", "2026-10-01", "eng", "", "", 1, 0, "https://mirror.example.org/x.zim", ())
    with pytest.raises(ZimloreError, match="not on kiwix.org"):
        catalog.download(entry, tmp_path, opener=never)
    assert list(tmp_path.iterdir()) == []


def test_a_runaway_stream_is_cut_at_the_declared_size_and_discarded(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    size = (served / NAME).stat().st_size
    peak = [0]

    def watch(done: int, _total: int) -> None:
        peak[0] = max(peak[0], done)

    with _serve(served, flood=3_000_000) as base, pytest.raises(ZimloreError, match="sent more than"):
        catalog.download(_at(entry, base), tmp_path / "zim", progress=watch)
    assert peak[0] <= size and list((tmp_path / "zim").iterdir()) == []


def test_a_download_past_its_deadline_stops_keeps_the_part_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    monkeypatch.setattr(catalog, "CHUNK", 4096)
    target = tmp_path / "zim"
    with _serve(served) as base:
        with pytest.raises(ZimloreError, match="deadline") as caught:
            catalog.download(_at(entry, base), target, deadline_seconds=0)
        assert "resumes" in caught.value.hint
        assert sorted(p.name for p in target.iterdir()) == [NAME + ".part"], "the part stays, the lock is released"
        got = catalog.download(_at(entry, base), target)
    assert got.read_bytes() == (served / NAME).read_bytes()


def test_a_file_bigger_than_the_free_space_is_refused_before_the_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: SimpleNamespace(total=1, used=1, free=10))
    seen: Seen = []
    with _serve(served, log=seen) as base, pytest.raises(ZimloreError, match="free") as caught:
        catalog.download(_at(entry, base), tmp_path / "zim")
    assert "prune" in caught.value.hint and _zim_requests(seen) == []
    assert list((tmp_path / "zim").iterdir()) == []


def test_a_body_cut_mid_chunk_is_a_clear_error_for_the_feed_and_the_zim(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    with _serve(served, cut_chunked=True) as base:
        with pytest.raises(ZimloreError, match="could not fetch") as feed:
            catalog.query(base=f"{base}/feed.zim")
        assert "retry" in feed.value.hint
        with pytest.raises(ZimloreError) as cut:
            catalog.download(_at(entry, base), tmp_path / "zim")
        assert "resumes" in cut.value.hint


def test_a_failed_install_keeps_the_verified_part_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    entry = _publish(served)

    def refuse(*_: object, **__: object) -> None:
        raise PermissionError(13, "access denied")

    target = tmp_path / "zim"
    seen: Seen = []
    with _serve(served, log=seen) as base:
        monkeypatch.setattr(os, "replace", refuse)
        with pytest.raises(ZimloreError, match="could not be installed") as caught:
            catalog.download(_at(entry, base), target)
        monkeypatch.undo()
        assert "no re-download is needed" in caught.value.hint
        assert sorted(p.name for p in target.iterdir()) == [NAME + ".part"], "verified bytes kept, lock released"
        seen.clear()
        got = catalog.download(_at(entry, base), target)
    assert got.read_bytes() == (served / NAME).read_bytes() and _zim_requests(seen) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (b"<totalResults>7", b"<totalResults>abc"),
        (b"<articleCount>59", b"<articleCount>1e3"),
        (b"<articleCount>59", b"<articleCount>-5"),
        (b'length="617472"', b'length="1.5"'),
        (b'length="617472"', 'length="²"'.encode()),
        (b"<totalResults>7", b"<totalResults>" + b"9" * 30),
    ],
)
def test_catalogue_numbers_that_are_not_whole_numbers_are_a_clear_error(old: bytes, new: bytes) -> None:
    assert old in FEED
    with pytest.raises(ZimloreError, match="not a whole number"):
        catalog.parse_feed(FEED.replace(old, new))
    metalink = b'<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file><size>3x</size><hash type="sha-256">'
    with pytest.raises(ZimloreError, match="not a whole number"):
        catalog.parse_metalink(metalink + b"a" * 64 + b"</hash></file></metalink>")


def test_the_metalink_size_and_hash_must_come_from_the_same_file_entry() -> None:
    ns = b'xmlns="urn:ietf:params:xml:ns:metalink"'
    mixed = b"<metalink " + ns + b'><file><size>3</size></file><file><size>9</size><hash type="sha-256">' + b"B" * 64
    parsed = catalog.parse_metalink(mixed + b"</hash></file></metalink>")
    assert (parsed.size, parsed.sha256) == (9, "b" * 64), "the first file has no hash; its size is not borrowed"


def _entry_at(file: str) -> catalog.CatalogEntry:
    url = f"https://download.kiwix.org/zim/{file}"
    return catalog.CatalogEntry("x", "x", "d", "eng", "", "", 1, 0, url, ())


@pytest.mark.parametrize("stem", ["CON", "nul", "Aux", "com1", "LPT9", "con.backup"])
def test_windows_device_names_are_not_file_names(stem: str) -> None:
    with pytest.raises(ZimloreError, match="will not create"):
        catalog.target_name(_entry_at(f"{stem}.zim"))


@pytest.mark.parametrize("name", ["a b.zim", "x%2e%2e.zim", "x:stream.zim", "ünï.zim", "-lead.zim"])
def test_odd_file_names_are_refused_and_catalogue_names_accepted(name: str) -> None:
    with pytest.raises(ZimloreError, match="will not create"):
        catalog.target_name(_entry_at(name))
    for good in ("devdocs_en_acme_2026-10.zim", "stackoverflow.com_en_all_2026-10.zim", "wikipedia_en_all_maxi.zim"):
        assert catalog.target_name(_entry_at(good)) == good


def test_control_characters_and_escape_sequences_are_stripped_from_catalogue_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert catalog.clean("a\x1b[31mred\x1b[0m\x1b]0;title\x07b\x1b\\c\x07\x00d\te") == "aredbcd e"
    title = "<title>Acme \u009b31mDocs‮!</title><updated>2026-10-01"
    hostile = FEED.replace(b"<title>Acme Docs</title><updated>2026-10-01", title.encode())
    entries, _ = catalog.parse_feed(hostile)
    assert entries[0].title == "Acme 31mDocs!"
    monkeypatch.setattr(catalog, "query", lambda *_a, **_k: catalog.parse_feed(hostile))
    code, out, _ = _cli(capsys, "catalog", "acme")
    assert code == 0 and "Acme 31mDocs!" in out and not any(c in out for c in "\u009b‮\x1b")


class _Reply:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _n: int = -1) -> bytes:
        return self.body


def _paged_feed(dates: list[str], requested: list[int]) -> catalog.Opener:
    def opener(request: Any) -> _Reply:
        query = parse_qs(urlsplit(request.full_url).query)
        start, count = int(query.get("start", ["0"])[0]), int(query["count"][0])
        requested.append(start)
        rows = "".join(
            f"<entry><id>urn:uuid:{n}</id><title>A</title><updated>{day}T00:00:00Z</updated><name>acme</name>"
            f'<link type="application/x-zim" href="https://download.kiwix.org/zim/acme_{n}.zim.meta4" length="1"/>'
            "</entry>"
            for n, day in enumerate(dates)
            if start <= n < start + count
        )
        feed = f'<feed xmlns="http://www.w3.org/2005/Atom"><totalResults>{len(dates)}</totalResults>{rows}</feed>'
        return _Reply(feed.encode())

    return opener


def test_the_newest_edition_is_found_whatever_order_and_page_it_arrives_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "PAGE_SIZE", 2)
    requested: list[int] = []
    dates = ["2026-03-01", "2026-01-01", "2026-05-01", "2026-02-01", "2026-04-01"]
    found = catalog.editions_of("acme", opener=_paged_feed(dates, requested))
    assert requested == [0, 2, 4] and len(found) == 5
    assert [e.date for e in catalog.latest(found)] == ["2026-05-01"]


def test_catalogue_dates_are_compared_as_dates() -> None:
    feed = FEED.replace(b"2026-10-01T00:00:00Z", b"2026-9-15T00:00:00Z")
    feed = feed.replace(b"2026-09-28T00:00:00Z", b"2026-10-01T00:00:00Z")
    entries, _ = catalog.parse_feed(feed)
    assert [e.date for e in catalog.latest(entries)] == ["2026-10-01"], "'2026-9-15' sorts after '2026-10-01' as text"


def test_download_never_replaces_an_existing_file_unless_told(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    target = tmp_path / "zim"
    target.mkdir()
    mine = target / NAME
    mine.write_bytes(b"PRECIOUS")
    seen: Seen = []
    with _serve(served, log=seen) as base:
        with pytest.raises(ZimloreError, match="not replacing") as caught:
            catalog.download(_at(entry, base), target)
        assert "--replace" in caught.value.hint
        size = (served / NAME).stat().st_size
        mine.write_bytes(b"P" * size)  # the right length, a record of some other hash
        manage.write_sidecar(mine, manage.Provenance("u", "n", "d", "00" * 32, size, "t", "get"))
        with pytest.raises(ZimloreError, match="not replacing"):
            catalog.download(_at(entry, base), target)  # a record of some OTHER content does not make it identical
    assert mine.read_bytes().startswith(b"P") and _zim_requests(seen) == []
    assert sorted(p.name for p in target.iterdir()) == [NAME, NAME + ".zimlore.json"], "no .part, no lock"


def test_an_identical_installed_file_is_a_no_op_that_says_so(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    target = tmp_path / "zim"
    seen: Seen = []
    with _serve(served, log=seen) as base:
        first = catalog.download_result(_at(entry, base), target)
        stamp = first.path.stat().st_mtime_ns
        again = catalog.download_result(_at(entry, base), target)
    assert (first.status, again.status) == ("installed", "already-installed")
    assert again.path.stat().st_mtime_ns == stamp and len(_zim_requests(seen)) == 1


def test_replace_swaps_the_file_and_its_sidecar(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    target = tmp_path / "zim"
    target.mkdir()
    old = target / NAME
    old.write_bytes(b"old bytes")
    manage.write_sidecar(old, manage.Provenance("u", "n", "d", manage.sha256_of(old), 9, "t", "add"))
    with _serve(served) as base:
        result = catalog.download_result(_at(entry, base), target, replace=True)
    assert result.status == "replaced" and result.path.read_bytes() == (served / NAME).read_bytes()
    record, _ = manage.read_sidecar(old)
    assert record is not None and record.added_by == "get" and record.sha256 == manage.sha256_of(old)


@pytest.mark.skipif(os.name != "nt", reason="only Windows refuses to replace a file another handle holds open")
def test_replacing_a_file_that_is_open_fails_before_anything_is_downloaded(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    target = tmp_path / "zim"
    target.mkdir()
    held = target / NAME
    held.write_bytes(b"in use")
    seen: Seen = []
    with (
        _serve(served, log=seen) as base,
        held.open("rb"),
        pytest.raises(ZimloreError, match="in use by another process") as caught,
    ):
        catalog.download(_at(entry, base), target, replace=True)
    assert "stop" in caught.value.hint and seen == [], "not even the .meta4 was requested"
    assert held.read_bytes() == b"in use" and sorted(p.name for p in target.iterdir()) == [NAME]


def test_the_meta4_is_fetched_with_the_catalogue_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    real = catalog._get
    pins: list[tuple[str, bool]] = []

    def spy(url: str, opener: Any = None, limit: int = 20_000_000, *, pinned: bool = False) -> bytes:
        pins.append((url.rsplit("/", 1)[-1], pinned))
        return real(url, opener, limit, pinned=pinned)

    monkeypatch.setattr(catalog, "_get", spy)
    with _serve(served) as base:
        catalog.download(_at(entry, base), tmp_path / "zim")
    assert pins == [(NAME + ".meta4", True)]
