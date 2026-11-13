"""The only code in this collection that touches the network, behind an injectable transport.

A `Transport` is a function from a URL to a `Response`; tests pass their own and never open a socket. The real
one (`urllib_transport`) is held to three rules that a draft's bytes being public does not relax:

- only `https` and only the two hosts the IETF serves drafts and metadata from, redirects included, so a
  redirect cannot send the importer somewhere the person did not name;
- a hard ceiling on the body, read in chunks, so a hostile or broken server cannot fill memory;
- a fixed User-Agent that names this package and carries nothing about the person.

`Fetcher` adds the courtesy the IETF asks of automated clients: one request per second, spaced from the end of
the previous request, a bounded retry on 429 and 5xx that honours `Retry-After`, and nothing else.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from primarysource import __version__
from primarysource.errors import LibError

DATATRACKER = "datatracker.ietf.org"
ARCHIVE = "www.ietf.org"
ALLOWED_HOSTS = (DATATRACKER, ARCHIVE)
USER_AGENT = f"primarysource-draft/{__version__}"
MAX_BODY = 8_000_000
INTERVAL = 1.0
RETRIES = 2
MAX_RETRY_WAIT = 30.0


@dataclass(frozen=True, slots=True)
class Response:
    """What a transport returns: the HTTP status, the body (at most `MAX_BODY` bytes), the content type and the
    `Retry-After` header if the server sent one. A transport returns 4xx and 5xx; it raises only when no HTTP
    answer came back at all."""

    status: int
    body: bytes
    content_type: str = ""
    retry_after: float | None = None


Transport = Callable[[str], Response]


def check_url(url: str) -> None:
    """Refuse a URL that is not https on an allowed host. Used before a request and again on every redirect."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
        raise LibError(f"refusing to fetch {url[:100]!r}: only https://{DATATRACKER} and https://{ARCHIVE}", "")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: urllib.request.Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> urllib.request.Request | None:
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP-date form is ignored; the fixed back-off applies


def urllib_transport(url: str, timeout: float = 30.0) -> Response:
    """GET `url` with the standard library, under the rules in the module docstring."""
    check_url(url)
    opener = urllib.request.build_opener(_Redirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})  # noqa: S310
    try:
        with opener.open(request, timeout=timeout) as reply:
            body = reply.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise LibError(f"{url} is larger than {MAX_BODY:,} bytes; refusing it", "")
            return Response(reply.status, body, reply.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        return Response(
            exc.code, b"", exc.headers.get("Content-Type", ""), _retry_after(exc.headers.get("Retry-After"))
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LibError(f"could not reach {urlsplit(url).hostname}: {exc}", "check the network and try again") from exc


class Fetcher:
    """Rate-limited, retrying GET over a transport. `clock` and `sleep` are injectable so tests take no time."""

    def __init__(
        self,
        transport: Transport = urllib_transport,
        interval: float = INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._transport = transport
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self.requests = 0

    def _wait(self) -> None:
        if self._last is not None:
            remaining = self._interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)

    def get(self, url: str) -> Response:
        """The response for `url`, which may be a 404 (the caller decides what that means). A 429 or 5xx is
        retried `RETRIES` times, then raised as a LibError that says to try later."""
        check_url(url)
        attempt = 0
        while True:
            self._wait()
            try:
                reply = self._transport(url)
            finally:
                self._last = self._clock()
                self.requests += 1
            if reply.status != 429 and reply.status < 500:
                return reply
            if attempt >= RETRIES:
                raise LibError(f"{urlsplit(url).hostname} answered {reply.status} for {url[:100]}", "try again later")
            attempt += 1
            self._sleep(min(reply.retry_after if reply.retry_after is not None else 5.0 * attempt, MAX_RETRY_WAIT))
