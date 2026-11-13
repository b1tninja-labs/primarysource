"""A polite, bounded fetcher: one request per second, https to named hosts only, a size ceiling, no surprises.

Private to the c2sp, bbf and ecma collections. It stands in for the core's `cl.fetch_pinned` (ROADMAP) and is
meant to be replaced by it. Nothing here writes a file: the importers verify the bytes against a pinned sha256
and then write.

The transport is injectable (`Transport`: URL and byte ceiling in, bytes out), so every importer test runs with
no network and the real one is only the default.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from http.client import HTTPMessage
from typing import IO

from primarysource.errors import LibError

Transport = Callable[[str, int], bytes]

MIN_INTERVAL = 1.0
TIMEOUT = 60.0
USER_AGENT = "primarysource-importer (+https://github.com/b1tninja-labs/primarysource)"


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


class Fetcher:
    """Fetches at most one URL per `min_interval` seconds through `transport`."""

    def __init__(
        self,
        hosts: Sequence[str],
        transport: Transport | None = None,
        *,
        min_interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._hosts = tuple(hosts)
        self._transport = transport or urllib_transport(self._hosts)
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self.requests = 0

    def get(self, url: str, max_bytes: int) -> bytes:
        """The body of `url`, or a `LibError` if it is not allowed, fails, or is larger than `max_bytes`."""
        check_url(url, self._hosts)
        if self._last is not None:
            wait = self._last + self._interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1
        body = self._transport(url, max_bytes)
        if len(body) > max_bytes:
            raise LibError(
                f"{url} is larger than {max_bytes} bytes", "the pinned file is smaller; do not import this"
            )
        return body


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify(data: bytes, expected: str, name: str) -> None:
    """Raise unless `data` hashes to `expected`; the message names both digests."""
    actual = sha256(data)
    if actual != expected:
        raise LibError(
            f"{name}: sha256 {actual} does not match the pinned {expected}",
            "the publisher changed the file or the download was altered; nothing was written",
        )
