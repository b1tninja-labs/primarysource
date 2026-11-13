"""The usb.ids importer behind an injected transport: pinning, politeness, refusals, nothing written on failure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from usbids_fixture import DIGEST, PIN, SAMPLE, FakeTransport

from primarysource.errors import LibError
from primarysource.usbids import importer, store
from primarysource.usbids.importer import Response, import_usbids

NO_SLEEP = {"sleep": lambda _s: None}


def run(base: Path, transport: FakeTransport | None = None, **kwargs: object) -> importer.Outcome:
    kwargs.setdefault("pin", PIN)
    return import_usbids(base=base, transport=transport or FakeTransport(), **NO_SLEEP, **kwargs)  # type: ignore[arg-type]


def test_the_pinned_snapshot_installs_exactly_as_served_with_a_manifest(tmp_path: Path) -> None:
    base = tmp_path / "usbids"
    out = run(base)
    assert out.status == "fetched" and out.pinned and out.sha256 == DIGEST and out.requests == 1
    assert (base / "usb.ids").read_bytes() == SAMPLE
    record = json.loads((base / "manifest.json").read_text(encoding="utf-8"))["file"]
    assert record["sha256"] == DIGEST and record["version"] == "2099.01.02" and record["pinned"] is True
    assert record["licence"] == "GPL-2.0-or-later OR BSD-3-Clause" and record["url"] == importer.SOURCES[0]
    assert record["counts"]["vendor"] == 3 and record["etag"] == '"v1"'
    assert sorted(p.name for p in base.iterdir()) == ["manifest.json", "usb.ids"], "no temp files left"


def test_one_request_with_an_identifying_agent_and_no_conditional_headers_the_first_time(tmp_path: Path) -> None:
    transport = FakeTransport()
    run(tmp_path / "usbids", transport)
    assert len(transport.calls) == 1
    url, headers = transport.calls[0]
    assert url.startswith("https://") and headers["User-Agent"].startswith("primarysource-usbids/")
    assert "If-None-Match" not in headers and "If-Modified-Since" not in headers


def test_a_second_import_is_conditional_and_a_304_changes_nothing(tmp_path: Path) -> None:
    base = tmp_path / "usbids"
    run(base)
    before = (base / "usb.ids").stat().st_mtime_ns
    transport = FakeTransport()
    out = run(base, transport)
    assert out.status == "unchanged" and out.sha256 == DIGEST and out.pinned
    assert transport.calls[0][1]["If-None-Match"] == '"v1"'
    assert transport.calls[0][1]["If-Modified-Since"] == "Fri, 02 Jan 2099 03:04:05 GMT"
    assert (base / "usb.ids").stat().st_mtime_ns == before
    forced = FakeTransport()
    assert run(base, forced, force=True).status == "identical"
    assert "If-None-Match" not in forced.calls[0][1]


def test_a_failing_first_source_falls_back_to_the_second_after_the_interval(tmp_path: Path) -> None:
    first, second = importer.SOURCES
    transport = FakeTransport(plan={first: Response(503, {}, b"")})
    naps: list[float] = []
    ticks = iter([100.0, 100.2, 100.2, 100.2])
    out = import_usbids(
        base=tmp_path / "usbids", transport=transport, pin=PIN, sleep=naps.append, clock=lambda: next(ticks)
    )
    assert out.url == second and out.requests == 2
    assert [c[0] for c in transport.calls] == [first, second]
    assert naps == [pytest.approx(0.8)], "the second request waits out the one-second interval"


def test_every_source_failing_names_each_failure_and_writes_nothing(tmp_path: Path) -> None:
    base = tmp_path / "usbids"
    plan = {url: Response(404, {}, b"") for url in importer.SOURCES}
    with pytest.raises(LibError, match="no source gave usb.ids: .*HTTP 404.*HTTP 404"):
        run(base, FakeTransport(plan=plan))
    assert not base.exists()


def test_a_transport_error_is_a_failure_of_that_source_only(tmp_path: Path) -> None:
    class Flaky(FakeTransport):
        def __call__(self, url: str, headers: object) -> Response:
            if url == importer.SOURCES[0]:
                raise LibError("could not reach it", "")
            return super().__call__(url, headers)  # type: ignore[arg-type]

    assert run(tmp_path / "usbids", Flaky()).url == importer.SOURCES[1]


def test_an_unpinned_snapshot_needs_latest_or_its_digest(tmp_path: Path) -> None:
    newer = SAMPLE.replace(b"2099.01.02", b"2099.02.03") + b"0c0c  Added Since\n"
    base = tmp_path / "usbids"
    with pytest.raises(LibError, match="serves snapshot 2099.02.03") as caught:
        run(base, FakeTransport(newer))
    assert "--latest" in caught.value.hint and not base.exists()
    out = run(base, FakeTransport(newer), latest=True)
    assert out.version == "2099.02.03" and not out.pinned
    other = tmp_path / "other"
    import hashlib

    digest = hashlib.sha256(newer).hexdigest()
    assert run(other, FakeTransport(newer), sha256=digest.upper()).sha256 == digest


def test_a_named_digest_that_is_not_the_body_refuses(tmp_path: Path) -> None:
    with pytest.raises(LibError, match="not the " + "0" * 64):
        run(tmp_path / "usbids", sha256="0" * 64)
    with pytest.raises(LibError, match="not a sha256"):
        run(tmp_path / "usbids", sha256="abc")


def test_the_pinned_version_with_other_bytes_is_refused_as_altered(tmp_path: Path) -> None:
    base = tmp_path / "usbids"
    with pytest.raises(LibError, match="damaged or altered"):
        run(base, FakeTransport(SAMPLE + b"0c0c  Injected\n"), latest=True)
    assert not base.exists()


@pytest.mark.parametrize("body", [b"<html>not found</html>\n", b"", b"0001  V\njunk line\n", b"0001  a\x00\n"])
def test_a_body_that_is_not_usb_ids_writes_nothing(tmp_path: Path, body: bytes) -> None:
    base = tmp_path / "usbids"
    with pytest.raises(LibError):
        run(base, FakeTransport(body), latest=True)
    assert not base.exists()


def test_a_refused_update_leaves_the_installed_file_alone(tmp_path: Path) -> None:
    base = tmp_path / "usbids"
    run(base)
    with pytest.raises(LibError):
        run(base, FakeTransport(b"junk\n"), force=True, latest=True)
    assert (base / "usb.ids").read_bytes() == SAMPLE
    assert store.load(base).sha256 == DIGEST


def test_an_oversize_body_is_a_failure_of_that_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importer, "MAX_BYTES", 100)
    with pytest.raises(LibError, match="is over 100 bytes"):
        run(tmp_path / "usbids")


def test_the_interval_is_never_under_one_second(tmp_path: Path) -> None:
    transport = FakeTransport()
    with pytest.raises(LibError, match="under 1 second"):
        run(tmp_path / "usbids", transport, interval=0.5)
    assert not transport.calls


def test_a_read_only_library_fetches_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_READONLY", "1")
    transport = FakeTransport()
    with pytest.raises(LibError, match="read-only"):
        run(tmp_path / "usbids", transport)
    assert not transport.calls


def test_only_https_sources_are_accepted(tmp_path: Path) -> None:
    transport = FakeTransport()
    with pytest.raises(LibError, match="https only"):
        run(tmp_path / "usbids", transport, sources=("http://www.linux-usb.org/usb.ids",))
    assert not transport.calls


def test_the_default_transport_refuses_a_url_outside_the_source_list() -> None:
    for url in ("http://www.linux-usb.org/usb.ids", "https://example.com/usb.ids", "file:///etc/passwd"):
        with pytest.raises(LibError, match="refusing to fetch"):
            importer.urllib_transport(url, {})


def test_the_main_entry_reports_an_error_with_exit_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PRIMARYSOURCE_HOME", str(tmp_path))
    down = FakeTransport(plan={u: Response(500, {}, b"") for u in importer.SOURCES})
    monkeypatch.setattr(
        importer, "import_usbids", lambda **kw: import_usbids(transport=down, sleep=lambda _s: None, **kw)
    )
    assert importer.main([]) == 1
    assert "error: no source gave usb.ids" in capsys.readouterr().err
