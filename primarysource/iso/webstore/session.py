"""One polite session: host allow-list, the collection's network settings, one request per second, and manual
redirects, so every hop is checked.

This is the only place a request is made. It is a state machine over a `Transport`; with a fake transport nothing
leaves the process.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager

from primarysource.errors import LibError
from primarysource.fetch import MIN_INTERVAL, USER_AGENT, check_url
from primarysource.iso.webstore.transport import HttpRequest, HttpResponse, StreamResponse, Transport, UrllibTransport
from primarysource.settings import require_network

COLLECTION = "iso"
BASE = "https://www.iso.org"
IDP = "https://idp.iso.org"
HOSTS = ("www.iso.org", "idp.iso.org")
MAX_REDIRECTS = 10
_ALGOLIA_HOST = re.compile(r"[a-z0-9]{6,16}-dsn\.algolia\.net")


def hosts_for(url: str) -> tuple[str, ...]:
    """The allow-list for `url`: the ISO hosts, plus the one Algolia host that url names, if it has the DSN shape."""
    host = urllib.parse.urlsplit(url).hostname or ""
    return (*HOSTS, host) if _ALGOLIA_HOST.fullmatch(host) else HOSTS


class WebstoreSession:
    """`request` and `stream` with the checks every call needs. No credentials here; the transport holds cookies."""

    def __init__(
        self,
        transport: Transport | None = None,
        *,
        environ: Mapping[str, str] | None = None,
        min_interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.transport: Transport = transport or UrllibTransport()
        self._environ = environ
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self.requests = 0

    def _begin(self, url: str) -> None:
        check_url(url, hosts_for(url))
        require_network(url, COLLECTION, environ=self._environ)
        if self._last is not None:
            wait = self._last + self._interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1

    @staticmethod
    def _prepare(request: HttpRequest) -> HttpRequest:
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en", **request.headers}
        return HttpRequest(request.method, request.url, headers, request.body)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        follow: bool = True,
    ) -> HttpResponse:
        """One logical request. A 301/302/303 is followed as a GET, a 307/308 with the same method, to a URL that
        passes the same host check, at most `MAX_REDIRECTS` times. Every hop counts against the interval."""
        current = HttpRequest(method.upper(), url, dict(headers or {}), body)
        for _ in range(MAX_REDIRECTS + 1):
            self._begin(current.url)
            response = self.transport.send(self._prepare(current))
            location = response.header("location")
            if not follow or response.status not in (301, 302, 303, 307, 308) or not location:
                return HttpResponse(response.status, response.headers, response.body, current.url)
            target = urllib.parse.urljoin(current.url, location)
            if response.status in (307, 308):
                current = HttpRequest(current.method, target, current.headers, current.body)
            else:
                kept = {
                    k: v for k, v in current.headers.items() if k.lower() not in ("content-type", "content-length")
                }
                current = HttpRequest("GET", target, kept, None)
        raise LibError(
            f"{url}: more than {MAX_REDIRECTS} redirects", "the sign-in flow changed; sign in in a browser"
        )

    def stream(self, url: str, *, headers: Mapping[str, str] | None = None) -> AbstractContextManager[StreamResponse]:
        """A GET whose body is read in pieces. No redirect is followed: a download that redirects is refused."""
        self._begin(url)
        return self.transport.stream(self._prepare(HttpRequest("GET", url, dict(headers or {}), None)))
