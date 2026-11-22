"""The HTTP seam of the webstore client: one small interface, so every test runs against a fake.

`Transport.send` makes exactly one request and never follows a redirect; the caller (`session.WebstoreSession`)
follows redirects itself, so each hop is checked against the host allow-list. `UrllibTransport` is the only real
implementation, and nothing in the test suite constructs it.
"""

from __future__ import annotations

import contextlib
import http.cookiejar
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import IO, Any, Protocol

from primarysource.errors import LibError

TIMEOUT = 60.0
COOKIE_HOST = "www.iso.org"
"""Only cookies of this host are exported by `Transport.cookies` (the identity provider's stay in memory)."""


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """A whole response. `headers` has lower-case names. A redirect is a response, not an exception."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    url: str

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class StreamResponse(Protocol):
    @property
    def status(self) -> int: ...

    def header(self, name: str) -> str | None: ...

    def read(self, size: int) -> bytes: ...


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...

    def stream(self, request: HttpRequest) -> AbstractContextManager[StreamResponse]: ...

    def cookies(self) -> dict[str, str]:
        """The `www.iso.org` cookies, name to value. Values are credentials: never print or log them."""
        ...

    def set_cookies(self, cookies: Mapping[str, str]) -> None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class _UrllibStream:
    def __init__(self, status: int, headers: Any, body: IO[bytes] | None) -> None:
        self.status = status
        self._headers = headers
        self._body = body

    def header(self, name: str) -> str | None:
        value = self._headers.get(name) if self._headers is not None else None
        return None if value is None else str(value)

    def read(self, size: int) -> bytes:
        return self._body.read(size) if self._body is not None else b""


class UrllibTransport:
    """urllib over https with a cookie jar and no automatic redirects. The default for real use only."""

    def __init__(self) -> None:
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar), _NoRedirect())

    def _open(self, request: HttpRequest) -> Any:
        prepared = urllib.request.Request(  # noqa: S310 - the session checked scheme and host
            request.url, data=request.body, headers=dict(request.headers), method=request.method
        )
        try:
            return self._opener.open(prepared, timeout=TIMEOUT)
        except urllib.error.HTTPError as exc:
            return exc  # a 3xx/4xx/5xx is a response here
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LibError(f"{request.method} {request.url}: {exc}", "check the network, then run it again") from exc

    def send(self, request: HttpRequest) -> HttpResponse:
        response = self._open(request)
        try:
            body: bytes = response.read()
            headers = {name.lower(): str(value) for name, value in response.headers.items()}
            return HttpResponse(
                int(response.status if hasattr(response, "status") else response.code), headers, body, request.url
            )
        finally:
            response.close()

    def stream(self, request: HttpRequest) -> AbstractContextManager[StreamResponse]:
        @contextlib.contextmanager
        def manager() -> Iterator[StreamResponse]:
            response = self._open(request)
            try:
                status = int(response.status if hasattr(response, "status") else response.code)
                yield _UrllibStream(status, response.headers, response)
            finally:
                response.close()

        return manager()

    def cookies(self) -> dict[str, str]:
        return {cookie.name: cookie.value or "" for cookie in self._jar if cookie.domain.lstrip(".") == COOKIE_HOST}

    def set_cookies(self, cookies: Mapping[str, str]) -> None:
        for name, value in cookies.items():
            self._jar.set_cookie(
                http.cookiejar.Cookie(
                    0,
                    name,
                    value,
                    None,
                    False,
                    COOKIE_HOST,
                    True,
                    False,
                    "/",
                    True,
                    True,
                    None,
                    False,
                    None,
                    None,
                    {},
                )
            )
