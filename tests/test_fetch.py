"""The pinned fetch (`primarysource.fetch`): URL checks, throttle, network settings, and the resumable download.

Invented bytes and a fake transport only: no network.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from primarysource.c2sp import _fetch as shim
from primarysource.errors import LibError
from primarysource.fetch import Fetcher, Response, check_url, verify
from primarysource.settings import NetworkDisabled

HOST = "files.invented.example"
HOSTS = (HOST,)
URL = f"https://{HOST}/pub/invented.bin"
DATA = bytes(range(256)) * 40  # 10240 invented bytes
PIN = hashlib.sha256(DATA).hexdigest()
ONLINE: dict[str, str] = {}


class FakeResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str], fail_after: int | None = None) -> None:
        self.status = status
        self._body = io.BytesIO(body)
        self._headers = headers
        self._fail_after = fail_after

    def header(self, name: str) -> str | None:
        return self._headers.get(name)

    def read(self, size: int) -> bytes:
        if self._fail_after is not None and self._body.tell() >= self._fail_after:
            raise ConnectionResetError("invented reset")
        if self._fail_after is not None:
            size = min(size, self._fail_after - self._body.tell())
        return self._body.read(size)


class FakeServer:
    """Serves `data`. `ranges=False` answers every Range with the whole file; `cut` ends the body early;
    `reset` raises mid-body; `length` overrides Content-Length."""

    def __init__(self, data: bytes = DATA, *, ranges: bool = True) -> None:
        self.data = data
        self.ranges = ranges
        self.cut: int | None = None
        self.reset: int | None = None
        self.length: int | None = None
        self.calls: list[tuple[str, int]] = []

    @contextlib.contextmanager
    def __call__(self, url: str, offset: int) -> Iterator[Response]:
        self.calls.append((url, offset))
        if offset and offset >= len(self.data):
            yield FakeResponse(416, b"", {})
            return
        if offset and self.ranges:
            body = self.data[offset:]
            headers = {"Content-Range": f"bytes {offset}-{len(self.data) - 1}/{len(self.data)}"}
            status = 206
        else:
            body, headers, status = self.data, {}, 200
        if self.cut is not None:
            body = body[: self.cut]
        headers["Content-Length"] = str(self.length if self.length is not None else len(body))
        yield FakeResponse(status, body, headers, self.reset)


def fetcher(server: FakeServer, **kwargs: object) -> Fetcher:
    return Fetcher(HOSTS, lambda url, n: DATA, stream=server, min_interval=0, environ=ONLINE, **kwargs)  # type: ignore[arg-type]


def test_the_c2sp_path_re_exports_the_core() -> None:
    assert shim.Fetcher is Fetcher
    assert shim.check_url is check_url
    assert shim.verify is verify


def test_only_https_to_a_named_host_on_the_default_port() -> None:
    check_url(URL, HOSTS)
    for bad in (
        f"http://{HOST}/x",
        "https://elsewhere.example/x",
        f"https://user:pw@{HOST}/x",
        f"https://{HOST}:8443/x",
    ):
        with pytest.raises(LibError):
            check_url(bad, HOSTS)


def test_one_request_per_interval() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    fetch = Fetcher(HOSTS, lambda url, n: b"x", clock=lambda: now[0], sleep=sleep, environ=ONLINE)
    for _ in range(3):
        fetch.get(URL, 10)
    assert sleeps == [1.0, 1.0]
    assert fetch.requests == 3


def test_offline_and_read_only_refuse_before_any_request() -> None:
    asked: list[str] = []

    def record(url: str, max_bytes: int) -> bytes:
        asked.append(url)
        return b""

    for env in ({"PRIMARYSOURCE_NETWORK": "offline"}, {"PRIMARYSOURCE_ECMA_READONLY": "1"}):
        fetch = Fetcher(HOSTS, record, collection="ecma", environ=env)
        with pytest.raises(NetworkDisabled):
            fetch.get(URL, 10)
    assert asked == []
    on_demand = Fetcher(
        HOSTS, lambda url, n: b"ok", collection="ecma", environ={"PRIMARYSOURCE_NETWORK": "on-demand"}
    )
    assert on_demand.get(URL, 10) == b"ok"


def test_a_body_over_the_ceiling_is_refused_and_verify_names_both_digests() -> None:
    with pytest.raises(LibError, match="larger than"):
        Fetcher(HOSTS, lambda url, n: b"x" * (n + 1), environ=ONLINE).get(URL, 5)
    verify(DATA, PIN, "invented.bin")
    with pytest.raises(LibError) as wrong:
        verify(DATA + b"!", PIN, "invented.bin")
    assert PIN in wrong.value.message


def test_download_verifies_then_replaces_and_leaves_no_part(tmp_path: Path) -> None:
    dest = tmp_path / "lib" / "invented.bin"
    server = FakeServer()
    seen: list[int] = []
    assert fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA), progress=lambda d, t: seen.append(d))
    assert dest.read_bytes() == DATA
    assert sorted(p.name for p in dest.parent.iterdir()) == ["invented.bin"]
    assert seen[-1] == len(DATA)
    assert not fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))  # already there: no request
    assert len(server.calls) == 1


def test_an_interrupted_download_resumes_from_the_part(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    server = FakeServer()
    server.reset = 4000
    with pytest.raises(LibError, match="interrupted at 4000") as failed:
        fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert "resumes" in failed.value.hint
    part = tmp_path / "invented.bin.part"
    assert part.stat().st_size == 4000
    assert not dest.exists()
    assert not (tmp_path / "invented.bin.part.lock").exists()
    server.reset = None
    assert fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert server.calls[-1] == (URL, 4000)
    assert dest.read_bytes() == DATA
    assert not part.exists()


def test_a_body_cut_short_keeps_the_part_for_resuming(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    server = FakeServer()
    server.cut, server.length = 1000, len(DATA)
    with pytest.raises(LibError, match="cut off at 1000"):
        fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    server.cut = server.length = None
    assert fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert dest.read_bytes() == DATA


def test_a_server_that_ignores_the_range_restarts_from_zero_never_splices(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    (tmp_path / "invented.bin.part").write_bytes(DATA[:3000])
    server = FakeServer(ranges=False)
    assert fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert dest.read_bytes() == DATA


def test_a_part_longer_than_the_server_file_is_restarted_after_416(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    (tmp_path / "invented.bin.part").write_bytes(b"Z" * 6000)
    server = FakeServer(DATA[:5000])  # the server's file is shorter than our part
    with pytest.raises(LibError, match="cut off at 5000"):
        fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert [offset for _, offset in server.calls] == [6000, 0]
    assert (tmp_path / "invented.bin.part").read_bytes() == DATA[:5000]
    assert not dest.exists()


def test_a_wrong_digest_is_discarded_and_nothing_takes_the_name(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    dest.write_bytes(b"older edition")
    altered = bytearray(DATA)
    altered[7] ^= 1
    with pytest.raises(LibError, match="discarded") as failed:
        fetcher(FakeServer(bytes(altered))).download(URL, dest, sha256=PIN, size=len(DATA))
    assert PIN in failed.value.message
    assert dest.read_bytes() == b"older edition"
    assert not (tmp_path / "invented.bin.part").exists()


def test_more_bytes_than_the_pin_allows_never_reach_the_disk(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    with pytest.raises(LibError, match="announces"):
        fetcher(FakeServer(DATA + b"extra")).download(URL, dest, sha256=PIN, size=len(DATA))
    server = FakeServer(DATA + b"extra")
    server.length = len(DATA)  # lies about its length
    with pytest.raises(LibError, match="more than the pinned"):
        fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert not (tmp_path / "invented.bin.part").exists()


def test_a_live_part_lock_stops_a_second_download(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    lock = tmp_path / "invented.bin.part.lock"
    lock.write_text("pid 1", "utf-8")
    server = FakeServer()
    with pytest.raises(LibError, match="another process"):
        fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))
    assert server.calls == []
    old = lock.stat().st_mtime - 7200
    os.utime(lock, (old, old))
    assert fetcher(server).download(URL, dest, sha256=PIN, size=len(DATA))  # stale: taken over
    assert not lock.exists()


def test_download_honours_offline_unless_the_file_is_already_in_place(tmp_path: Path) -> None:
    dest = tmp_path / "invented.bin"
    server = FakeServer()
    offline = Fetcher(HOSTS, stream=server, collection="ecma", environ={"PRIMARYSOURCE_ECMA_NETWORK": "offline"})
    with pytest.raises(NetworkDisabled):
        offline.download(URL, dest, sha256=PIN, size=len(DATA))
    assert server.calls == []
    dest.write_bytes(DATA)
    assert not offline.download(URL, dest, sha256=PIN, size=len(DATA))


def test_a_download_is_throttled_with_the_other_requests(tmp_path: Path) -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    server = FakeServer()
    fetch = Fetcher(HOSTS, lambda url, n: b"x", stream=server, clock=lambda: now[0], sleep=sleep, environ=ONLINE)
    fetch.get(URL, 10)
    fetch.download(URL, tmp_path / "invented.bin", sha256=PIN, size=len(DATA))
    assert sleeps == [1.0]
    assert fetch.requests == 2
