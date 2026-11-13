"""The pinned fetch: polite, bounded, and checked before anything is parsed or kept.

- https only, to named hosts, no credentials, the default port; a redirect is followed only to a URL that passes
  the same check;
- one request per `min_interval` seconds (one per second by default) per `Fetcher`;
- a byte ceiling on every body; the pinned sha256 is checked (`verify`) before the bytes are parsed or written;
- the collection's network settings (`primarysource.settings`) are honoured: offline or read-only refuses before a
  request is made;
- `Fetcher.download` brings a large file to disk as zimlore does: a `<name>.part` written under an `O_EXCL`
  `<name>.part.lock`, resumed with a Range request, verified against the pinned size and sha256, and only then put
  in place with `os.replace`. A failed or interrupted download leaves a `.part`, never a file that looks complete.

Lifted from `primarysource/c2sp/_fetch.py` (bbf and ecma import it there, through a re-export) and zimlore's
`catalog.py` (`_acquire_lock`, `_transfer`, `download_result`). Both transports are injectable, so every test runs
with no network; the urllib ones are only the defaults.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, Protocol

from primarysource.errors import LibError
from primarysource.fsutil import CHUNK, Lock, replace, sha256, sha256_file, write_lock
from primarysource.settings import require_network

__all__ = [
    "MIN_INTERVAL",
    "PART_LOCK_STALE_SECONDS",
    "TIMEOUT",
    "USER_AGENT",
    "Fetcher",
    "Response",
    "StreamTransport",
    "Transport",
    "check_url",
    "sha256",
    "urllib_stream_transport",
    "urllib_transport",
    "verify",
]

Transport = Callable[[str, int], bytes]
"""URL and byte ceiling in, the whole body out (at most the ceiling plus one byte)."""

MIN_INTERVAL = 1.0
TIMEOUT = 60.0
USER_AGENT = "primarysource-importer (+https://github.com/b1tninja-labs/primarysource)"
PART_LOCK_STALE_SECONDS = 3600.0
"""A `.part.lock` is touched on every chunk, so one untouched this long belongs to a download that died."""

_RETRY = "run the same command again: it resumes from the .part"


class Response(Protocol):
    """What a `StreamTransport` yields: a status, headers, and a body read in pieces."""

    @property
    def status(self) -> int: ...

    def header(self, name: str) -> str | None: ...

    def read(self, size: int) -> bytes: ...


StreamTransport = Callable[[str, int], AbstractContextManager[Response]]
"""URL and start offset in (0: the whole file; otherwise a `Range: bytes=<offset>-` request), a response out. A
416 is a response with status 416, not an exception; any other failure raises `LibError` or `OSError`."""


def check_url(url: str, hosts: Sequence[str]) -> None:
    """Refuse anything but `https://<host>/...` with a host from `hosts`, no credentials and no odd port."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in hosts or parts.username or parts.password:
        raise LibError(f"refusing to fetch {url!r}", f"only https from {', '.join(hosts)} is allowed")
    if parts.port not in (None, 443):
        raise LibError(f"refusing to fetch {url!r}", "only the default https port is allowed")


class _Guard(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to a URL that passes `check_url`."""

    def __init__(self, hosts: Sequence[str]) -> None:
        self._hosts = hosts

    def redirect_request(
        self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> urllib.request.Request | None:
        check_url(newurl, self._hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(hosts: Sequence[str]) -> Transport:
    """The real transport: urllib over https, redirects checked, the body read up to the ceiling plus one byte."""
    opener = urllib.request.build_opener(_Guard(hosts))

    def fetch(url: str, max_bytes: int) -> bytes:
        check_url(url, hosts)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - checked above
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                body: bytes = response.read(max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise LibError(f"{url}: HTTP {exc.code}", "retry later, or import the file by hand with --file") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LibError(f"{url}: {exc}", "check the network, or import the file by hand with --file") from exc
        return body

    return fetch


class _UrllibResponse:
    def __init__(self, status: int, headers: Any, body: IO[bytes] | None) -> None:
        self.status = status
        self._headers = headers
        self._body = body

    def header(self, name: str) -> str | None:
        return self._headers.get(name) if self._headers is not None else None

    def read(self, size: int) -> bytes:
        return self._body.read(size) if self._body is not None else b""


def urllib_stream_transport(hosts: Sequence[str]) -> StreamTransport:
    """The real streaming transport: urllib over https, redirects checked, a Range header when resuming."""
    opener = urllib.request.build_opener(_Guard(hosts))

    @contextlib.contextmanager
    def stream(url: str, offset: int) -> Iterator[Response]:
        check_url(url, hosts)
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - checked above
        try:
            response = opener.open(request, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            if exc.code == 416:
                yield _UrllibResponse(416, exc.headers, None)
                return
            raise LibError(f"{url}: HTTP {exc.code}", "retry later") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LibError(f"{url}: {exc}", "check the network, then run the same command again") from exc
        with response:
            yield _UrllibResponse(getattr(response, "status", 200), response.headers, response)

    return stream


def _range_start(response: Response) -> int | None:
    match = re.fullmatch(r"bytes (\d+)-\d+/(?:\d+|\*)", response.header("Content-Range") or "", re.ASCII)
    return int(match.group(1)) if match else None


def _content_length(response: Response) -> int | None:
    announced = response.header("Content-Length")
    return int(announced) if announced and announced.isascii() and announced.isdigit() else None


class Fetcher:
    """Fetches at most one URL per `min_interval` seconds, to `hosts` only, while the settings allow the network.

    `collection` and `legacy_app` choose whose network settings apply (`primarysource.settings`); with neither,
    only `PRIMARYSOURCE_NETWORK` and `PRIMARYSOURCE_READONLY` do. They are read at each request.
    """

    def __init__(
        self,
        hosts: Sequence[str],
        transport: Transport | None = None,
        *,
        stream: StreamTransport | None = None,
        min_interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        collection: str | None = None,
        legacy_app: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._hosts = tuple(hosts)
        self._transport = transport or urllib_transport(self._hosts)
        self._stream = stream or urllib_stream_transport(self._hosts)
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._collection = collection
        self._legacy_app = legacy_app
        self._environ = environ
        self._last: float | None = None
        self.requests = 0

    def _begin(self, url: str) -> None:
        """Check the URL and the settings, then wait out the interval and count the request."""
        check_url(url, self._hosts)
        require_network(url, self._collection, self._legacy_app, self._environ)
        if self._last is not None:
            wait = self._last + self._interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1

    def get(self, url: str, max_bytes: int) -> bytes:
        """The body of `url`, or a `LibError` if it is not allowed, fails, or is larger than `max_bytes`."""
        self._begin(url)
        body = self._transport(url, max_bytes)
        if len(body) > max_bytes:
            raise LibError(
                f"{url} is larger than {max_bytes} bytes", "the pinned file is smaller; do not import this"
            )
        return body

    def download(
        self,
        url: str,
        dest: Path,
        *,
        sha256: str,
        size: int,
        progress: Callable[[int, int], None] | None = None,
        stale_lock_seconds: float = PART_LOCK_STALE_SECONDS,
    ) -> bool:
        """Bring `dest` to the pinned `size` and `sha256`. True if a download put it there, False if it already was.

        The bytes go to `<dest>.part` under the lock `<dest>.part.lock`; an existing `.part` is resumed. Only a
        file of the pinned size and digest is moved to `dest`, with `os.replace`; a mismatch discards the `.part`
        and raises. An existing `dest` that is not the pinned file is replaced only by a verified download.
        """
        check_url(url, self._hosts)
        if dest.is_file() and dest.stat().st_size == size and sha256_file(dest) == sha256:
            return False
        require_network(url, self._collection, self._legacy_app, self._environ)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        lock_path = part.with_name(part.name + ".lock")
        with write_lock(lock_path, stale_after=stale_lock_seconds, what=str(part)) as lock:
            done, digest = self._transfer(url, part, lock, size, progress)
            if done != size or digest != sha256:
                part.unlink(missing_ok=True)
                raise LibError(
                    f"{url}: downloaded {done} bytes with sha256 {digest}, expected {size} bytes with the pinned "
                    f"{sha256}; the download was discarded",
                    "retry; if it persists the publisher changed the file or the download was altered",
                )
            try:
                replace(part, dest)
            except OSError as exc:
                raise LibError(
                    f"the verified download of {url} could not be moved to {dest} ({exc})",
                    f"it is kept as {part}; free {dest} and run the same command again (no re-download is needed)",
                ) from exc
        return True

    def _transfer(
        self, url: str, part: Path, lock: Lock, size: int, progress: Callable[[int, int], None] | None
    ) -> tuple[int, str]:
        """Bring `part` to `size` bytes and return (bytes, sha256 of the whole file).

        An existing `.part` is re-hashed and resumed with a Range request. A server that refuses the range (200
        instead of 206, a wrong Content-Range, 416) makes the download start over from byte zero, never splice.
        Never more than `size` bytes reach the disk.
        """
        for _ in range(2):
            digest = hashlib.sha256()
            offset = part.stat().st_size if part.exists() else 0
            if offset > size:  # longer than the file can be: not a prefix of it
                part.unlink()
                offset = 0
            if offset:
                with part.open("rb") as prefix:
                    while chunk := prefix.read(CHUNK):
                        digest.update(chunk)
                        lock.touch()
            if offset == size:
                return offset, digest.hexdigest()  # a complete .part: the digest check decides
            self._begin(url)
            try:
                with self._stream(url, offset) as response:
                    status = response.status
                    if status == 416:
                        if not offset:
                            raise LibError(f"{url}: HTTP 416 for the whole file", "retry later")
                        part.unlink(missing_ok=True)  # the server's file is shorter than our part
                        continue
                    if status not in (200, 206):
                        raise LibError(f"{url}: HTTP {status}", "retry later")
                    if offset and not (status == 206 and _range_start(response) == offset):
                        part.unlink(missing_ok=True)
                        if status != 200:
                            continue
                        digest, offset = hashlib.sha256(), 0  # range refused: this 200 is the whole file
                    elif not offset and status != 200:
                        raise LibError(f"{url}: HTTP {status} for a request without a range", "retry later")
                    return self._receive(url, response, part, lock, size, offset, digest, progress)
            except (OSError, http.client.HTTPException, ValueError) as exc:
                raise LibError(f"download of {url} failed ({exc})", _RETRY) from exc
        raise LibError(f"the server for {url} kept refusing to serve the file", "retry later")

    @staticmethod
    def _receive(
        url: str,
        response: Response,
        part: Path,
        lock: Lock,
        size: int,
        offset: int,
        digest: hashlib._Hash,
        progress: Callable[[int, int], None] | None,
    ) -> tuple[int, str]:
        promised = _content_length(response)
        if promised is not None and promised > size - offset:
            part.unlink(missing_ok=True)
            raise LibError(
                f"{url}: the server announces {promised} bytes where the pin allows {size - offset}",
                "the server is serving a different file; nothing was kept",
            )
        done = offset
        try:
            with part.open("ab" if offset else "wb") as out:
                while chunk := response.read(min(CHUNK, size - done + 1)):
                    if done + len(chunk) > size:
                        out.close()
                        part.unlink(missing_ok=True)
                        raise LibError(
                            f"{url}: the server sent more than the pinned {size} bytes; discarded",
                            "the server is serving a different file",
                        )
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    lock.touch()
                    if progress:
                        progress(done, size)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise LibError(f"download of {url} was interrupted at {done} of {size} bytes ({exc})", _RETRY) from exc
        if done < size:
            raise LibError(f"download of {url} was cut off at {done} of {size} bytes", _RETRY)
        return done, digest.hexdigest()


def verify(data: bytes, expected: str, name: str) -> None:
    """Raise unless `data` hashes to `expected`; the message names both digests."""
    actual = sha256(data)
    if actual != expected:
        raise LibError(
            f"{name}: sha256 {actual} does not match the pinned {expected}",
            "the publisher changed the file or the download was altered; nothing was written",
        )
