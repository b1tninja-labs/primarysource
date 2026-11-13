from __future__ import annotations

import hashlib
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest
from zimfixture import build_zim

from primarysource.zim import catalog, manage
from primarysource.zim.errors import ZimloreError

# The shape below is the live feed's (measured 2026-11-07); the entries and numbers are invented.
FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/terms/">
  <totalResults>7</totalResults><startIndex>0</startIndex><itemsPerPage>3</itemsPerPage>
  <entry>
    <id>urn:uuid:1</id><title>Acme Docs</title><updated>2026-10-01T00:00:00Z</updated>
    <summary>Acme documentation, by DevDocs</summary><language>eng</language><name>devdocs_en_acme</name>
    <tags>devdocs;acme;_ftindex:no;_pictures:yes</tags><articleCount>59</articleCount>
    <author><name>DevDocs</name></author>
    <link rel="http://opds-spec.org/acquisition/open-access" type="application/x-zim"
          href="https://lb.download.kiwix.org/zim/devdocs/devdocs_en_acme_2026-10.zim.meta4" length="617472" />
  </entry>
  <entry>
    <id>urn:uuid:2</id><title>Acme Docs</title><updated>2026-09-28T00:00:00Z</updated>
    <language>eng</language><name>devdocs_en_acme</name><articleCount>58</articleCount>
    <link type="application/x-zim" href="https://lb.download.kiwix.org/zim/devdocs/devdocs_en_acme_2026-09.zim.meta4"
          length="600000" />
  </entry>
  <entry>
    <id>urn:uuid:3</id><title>No ZIM here</title><updated>2026-09-28T00:00:00Z</updated><name>weird</name>
    <link type="text/html" href="https://example.org/" />
  </entry>
</feed>"""


def test_the_feed_parses_and_drops_entries_without_a_zim_link() -> None:
    entries, total = catalog.parse_feed(FEED)
    assert total == 7 and [e.date for e in entries] == ["2026-10-01", "2026-09-28"]
    first = entries[0]
    assert first.url == "https://lb.download.kiwix.org/zim/devdocs/devdocs_en_acme_2026-10.zim"
    assert first.tags == ("devdocs", "acme"), "scraper-internal tags are not shown"
    assert (first.articles, first.approx_bytes, first.creator) == (59, 617472, "DevDocs")
    assert [e.date for e in catalog.latest(entries)] == ["2026-10-01"]


def test_a_catalogue_that_is_not_xml_is_an_error() -> None:
    with pytest.raises(ZimloreError, match="valid XML"):
        catalog.parse_feed(b"<html>captive portal")


def test_query_builds_the_url_and_goes_through_the_opener() -> None:
    seen: list[str] = []

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _n: int = -1) -> bytes:
            return FEED

    def opener(request: object) -> Reply:
        seen.append(request.full_url)  # type: ignore[attr-defined]
        return Reply()

    entries, total = catalog.query("acme", language="eng", count=5, opener=opener)
    assert total == 7 and len(entries) == 2
    assert seen == ["https://opds.library.kiwix.org/catalog/v2/entries?count=5&q=acme&lang=eng"]


def test_plain_http_to_a_remote_host_is_refused() -> None:
    with pytest.raises(ZimloreError, match="only https"):
        catalog.query(base="http://example.org/catalog")


def test_metalink_needs_a_sha256() -> None:
    good = b'<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file><size>3</size><hash type="sha-256">' + b"a" * 64
    parsed = catalog.parse_metalink(good + b"</hash></file></metalink>")
    assert (parsed.size, parsed.sha256) == (3, "a" * 64)
    with pytest.raises(ZimloreError, match="no size and SHA-256"):
        catalog.parse_metalink(
            b'<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file><size>3</size></file></metalink>'
        )


@contextmanager
def _serve(
    directory: Path,
    lie_about: str = "",
    *,
    ignore_range: bool = False,
    range_status: int = 0,
    wrong_content_range: bool = False,
    drop_after: int | None = None,
    extra: bytes = b"",
    hide_length: bool = False,
    redirects: dict[str, str] | None = None,
    flood: int = 0,
    cut_chunked: bool = False,
    log: list[tuple[str, str | None]] | None = None,
) -> Iterator[str]:
    """A local mirror. `ignore_range` answers a Range request with 200 and the whole file; `range_status` answers
    it with that error; `wrong_content_range` sends a 206 that starts at the wrong byte; `drop_after` sends that
    many bytes of the FIRST .zim response and closes the connection; `extra` appends bytes beyond the file, with
    or without a Content-Length that admits them; `redirects` maps a request path (query ignored) to a Location;
    `flood` answers a .zim request with that many bytes of chunked, length-less junk; `cut_chunked` sends one
    chunk of a chunked body and closes without the terminating chunk. `log` records (path, Range header) of
    every request."""
    state = {"drop": drop_after}

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802
            requested = self.headers.get("Range")
            if log is not None:
                log.append((self.path, requested))
            route = self.path.split("?")[0]
            if redirects and route in redirects:
                self.send_response(302)
                self.send_header("Location", redirects[route])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not route.endswith(".zim"):
                super().do_GET()
                return
            if flood or cut_chunked:
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    if cut_chunked:
                        self.wfile.write(b"5\r\n01234\r\n")
                        return
                    sent = 0
                    while sent < flood:
                        size = min(1 << 16, flood - sent)
                        self.wfile.write(b"%x\r\n" % size + b"x" * size + b"\r\n")
                        sent += size
                    self.wfile.write(b"0\r\n\r\n")
                except OSError:
                    pass
                return
            if lie_about:
                body = b"not the file the metalink describes"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            data = (directory / self.path.lstrip("/")).read_bytes()
            start, status = 0, 200
            if requested and not ignore_range:
                if range_status:
                    self.send_error(range_status)
                    return
                start, status = int(requested.removeprefix("bytes=").rstrip("-")), 206
            body = data[start:]
            self.send_response(status)
            if status == 206:
                shown = start + 1 if wrong_content_range else start
                self.send_header("Content-Range", f"bytes {shown}-{len(data) - 1}/{len(data)}")
            if not hide_length:
                self.send_header("Content-Length", str(len(body) + len(extra)))
            self.end_headers()
            if state["drop"] is not None:
                self.wfile.write(body[: state["drop"]])
                state["drop"] = None
                return
            self.wfile.write(body + extra)

    server = HTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _publish(directory: Path) -> catalog.CatalogEntry:
    path = build_zim(directory, "devdocs_en_acme_2026-10.zim")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = (
        '<metalink xmlns="urn:ietf:params:xml:ns:metalink"><file name="x.zim">'
        f'<size>{path.stat().st_size}</size><hash type="sha-256">{digest}</hash></file></metalink>'
    )
    (directory / "devdocs_en_acme_2026-10.zim.meta4").write_text(meta, encoding="utf-8")
    return catalog.CatalogEntry("devdocs_en_acme", "Acme", "2026-10-01", "eng", "", "", 1, 0, "", ())


def test_download_verifies_size_and_sha256_then_installs(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    progress: list[tuple[int, int]] = []
    with _serve(served) as base:
        entry = catalog.CatalogEntry(**{**entry.__dict__, "url": f"{base}/devdocs_en_acme_2026-10.zim"})
        got = catalog.download(entry, tmp_path / "home" / "zim", progress=lambda d, t: progress.append((d, t)))
    assert got.read_bytes() == (served / "devdocs_en_acme_2026-10.zim").read_bytes()
    assert got.name == "devdocs_en_acme_2026-10.zim" and not list(got.parent.glob("*.part"))
    assert progress[-1][0] == progress[-1][1], "progress ends at the verified size"


def test_a_mismatching_download_is_discarded_and_never_named_zim(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    with _serve(served, lie_about="body") as base:
        entry = catalog.CatalogEntry(**{**entry.__dict__, "url": f"{base}/devdocs_en_acme_2026-10.zim"})
        with pytest.raises(ZimloreError, match="was discarded"):
            catalog.download(entry, tmp_path / "zim")
    assert list((tmp_path / "zim").iterdir()) == [], "neither a .zim nor a .part may remain"


def test_an_unreachable_catalogue_is_a_clear_error(tmp_path: Path) -> None:
    class Dead(BaseHTTPRequestHandler):
        pass

    with pytest.raises(ZimloreError, match="could not fetch"):
        catalog.query(base="http://127.0.0.1:9/none")


def test_a_download_of_the_right_size_but_the_wrong_bytes_is_discarded(tmp_path: Path) -> None:
    """Size alone is not verification: flip one byte and keep the length."""
    served = tmp_path / "served"
    entry = _publish(served)
    zim = served / "devdocs_en_acme_2026-10.zim"
    data = bytearray(zim.read_bytes())
    data[-1] ^= 0xFF
    zim.write_bytes(bytes(data))
    with _serve(served) as base:
        entry = catalog.CatalogEntry(**{**entry.__dict__, "url": f"{base}/devdocs_en_acme_2026-10.zim"})
        with pytest.raises(ZimloreError, match="sha256"):
            catalog.download(entry, tmp_path / "zim")
    assert list((tmp_path / "zim").iterdir()) == []


def test_a_download_leaves_a_provenance_sidecar_with_the_verified_hash(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    with _serve(served) as base:
        entry = catalog.CatalogEntry(**{**entry.__dict__, "url": f"{base}/devdocs_en_acme_2026-10.zim"})
        got = catalog.download(entry, tmp_path / "zim")
    record, problem = manage.read_sidecar(got)
    assert problem == "" and record is not None
    assert (record.added_by, record.catalogue_name, record.catalogue_date) == ("get", "devdocs_en_acme", "2026-10-01")
    assert record.source == entry.url and record.sha256 == manage.sha256_of(got) and record.size == got.stat().st_size


# --- resumable downloads, the lock, the size cap ------------------------------------------------------------

NAME = "devdocs_en_acme_2026-10.zim"


def _at(entry: catalog.CatalogEntry, base: str) -> catalog.CatalogEntry:
    return catalog.CatalogEntry(**{**entry.__dict__, "url": f"{base}/{NAME}"})


def _zim_requests(seen: list[tuple[str, str | None]]) -> list[str | None]:
    return [rng for path, rng in seen if path.endswith(".zim")]


def test_an_interrupted_download_resumes_with_a_range_request_and_verifies_the_whole_file(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    whole = (served / NAME).read_bytes()
    half = len(whole) // 2
    target = tmp_path / "zim"
    seen: list[tuple[str, str | None]] = []
    with _serve(served, drop_after=half, log=seen) as base:
        entry = _at(entry, base)
        with pytest.raises(ZimloreError) as cut:
            catalog.download(entry, target)
        assert "resumes" in cut.value.hint
        assert (target / (NAME + ".part")).stat().st_size == half, "the received half is kept"
        assert sorted(p.name for p in target.iterdir()) == [NAME + ".part"], "no .zim, and the lock is released"
        got = catalog.download(entry, target)
    assert got.read_bytes() == whole and sorted(p.name for p in target.iterdir()) == [NAME, NAME + ".zimlore.json"]
    assert _zim_requests(seen) == [None, f"bytes={half}-"]
    record, _ = manage.read_sidecar(got)
    assert record is not None and record.sha256 == hashlib.sha256(whole).hexdigest() and record.size == len(whole)


def test_resuming_hashes_the_prefix_too_so_a_wrong_prefix_is_caught(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    size = (served / NAME).stat().st_size
    target = tmp_path / "zim"
    target.mkdir()
    (target / (NAME + ".part")).write_bytes(b"\0" * (size // 2))
    seen: list[tuple[str, str | None]] = []
    with _serve(served, log=seen) as base, pytest.raises(ZimloreError, match="sha256"):
        catalog.download(_at(entry, base), target)
    assert _zim_requests(seen) == [f"bytes={size // 2}-"], "it did resume; the hash over the whole file caught it"
    assert list(target.iterdir()) == []


def test_a_mirror_that_refuses_the_range_restarts_the_download_from_zero(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    whole = (served / NAME).read_bytes()
    half = len(whole) // 2
    cases: list[tuple[dict[str, Any], list[str | None]]] = [
        ({"ignore_range": True}, [f"bytes={half}-"]),  # 200: the response itself is used from byte zero
        ({"range_status": 416}, [f"bytes={half}-", None]),  # 416: ask again without a Range
        ({"wrong_content_range": True}, [f"bytes={half}-", None]),  # 206 from the wrong byte: never spliced
    ]
    for number, (options, expected) in enumerate(cases):
        target = tmp_path / f"zim{number}"
        target.mkdir()
        (target / (NAME + ".part")).write_bytes(b"\0" * half)  # a prefix that is NOT the file's
        seen: list[tuple[str, str | None]] = []
        with _serve(served, log=seen, **options) as base:
            got = catalog.download(_at(entry, base), target)
        assert got.read_bytes() == whole, options
        assert _zim_requests(seen) == expected, options


def test_a_part_longer_than_the_file_is_not_a_prefix_and_is_restarted(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    whole = (served / NAME).read_bytes()
    target = tmp_path / "zim"
    target.mkdir()
    (target / (NAME + ".part")).write_bytes(b"x" * (len(whole) + 10))
    seen: list[tuple[str, str | None]] = []
    with _serve(served, log=seen) as base:
        got = catalog.download(_at(entry, base), target)
    assert got.read_bytes() == whole and _zim_requests(seen) == [None]


def test_a_complete_part_is_verified_without_asking_the_server_again(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    whole = (served / NAME).read_bytes()
    target = tmp_path / "zim"
    target.mkdir()
    (target / (NAME + ".part")).write_bytes(whole)
    seen: list[tuple[str, str | None]] = []
    with _serve(served, log=seen) as base:
        got = catalog.download(_at(entry, base), target)
    assert got.read_bytes() == whole and _zim_requests(seen) == []


def test_a_held_lock_stops_a_second_download_and_a_stale_one_is_reported_not_broken(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    target = tmp_path / "zim"
    target.mkdir()
    lock = target / (NAME + ".part.lock")
    lock.write_text("pid 1\n")
    part = target / (NAME + ".part")
    part.write_bytes(b"abc")
    seen: list[tuple[str, str | None]] = []
    with _serve(served, log=seen) as base:
        entry = _at(entry, base)
        with pytest.raises(ZimloreError, match="another zimlore") as held:
            catalog.download(entry, target)
        assert "must not write one .part" in held.value.hint
        old = time.time() - 7200
        os.utime(lock, (old, old))
        with pytest.raises(ZimloreError, match="120 minutes old") as stale:
            catalog.download(entry, target)
        assert str(lock) in stale.value.hint and "delete" in stale.value.hint
        assert lock.exists() and part.read_bytes() == b"abc", "a lock we did not take is never removed or bypassed"
        with pytest.raises(ZimloreError, match="another zimlore"):
            catalog.download(entry, target, stale_lock_seconds=10_000)  # the age is a parameter, not a constant
    assert seen == [], "the refusal happens before any request"


def test_a_server_that_sends_more_than_the_metalink_allows_is_refused(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    seen: list[tuple[str, str | None]] = []
    # Content-Length is checked before the first byte; without one the stream itself is capped
    with _serve(served, extra=b"x" * 7, log=seen) as base, pytest.raises(ZimloreError, match="announces"):
        catalog.download(_at(entry, base), tmp_path / "a")
    with (
        _serve(served, extra=b"x" * 7, hide_length=True) as base,
        pytest.raises(ZimloreError, match="sent more than"),
    ):
        catalog.download(_at(entry, base), tmp_path / "b")
    assert list((tmp_path / "a").iterdir()) == [] and list((tmp_path / "b").iterdir()) == []


def test_the_sidecar_records_who_asked_for_the_download(tmp_path: Path) -> None:
    served = tmp_path / "served"
    entry = _publish(served)
    with _serve(served) as base:
        got = catalog.download(_at(entry, base), tmp_path / "zim", added_by="sync")
    record, _ = manage.read_sidecar(got)
    assert record is not None and record.added_by == "sync"


def test_tag_and_max_size_filters_reach_the_catalogue_url() -> None:
    seen: list[str] = []

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _n: int = -1) -> bytes:
            return FEED

    def opener(request: object) -> Reply:
        seen.append(request.full_url)  # type: ignore[attr-defined]
        return Reply()

    catalog.query("", tag="devdocs", max_bytes=1_000_000, count=5, opener=opener)
    assert seen == ["https://opds.library.kiwix.org/catalog/v2/entries?count=5&lang=eng&tag=devdocs&maxsize=1000000"]
    seen.clear()
    catalog.query("flask", count=5, opener=opener)
    assert "tag=" not in seen[0] and "maxsize" not in seen[0], "filters are sent only when asked for"
