"""The wire, behind an interface: every client in this package talks to a `Transport`, and tests use a fake.

- `HttpRequest` / `HttpResponse`: plain values. Redirects are NOT followed by the default transport, because the
  cart-add answers 302 and the client wants to see where to.
- `Transport`: `send` (a bounded body), `open_stream` (a download, read in pieces), `cookie` / `set_cookie` (the
  Magento `form_key` is a cookie the browser invents; the session cookie is the login).
- `PoliteTransport`: wraps any transport with the settings gate (`primarysource.settings.require_network`,
  collection `iec`), one request per second, and a generic User-Agent with no personal data.
- `UrllibTransport`: the default, https only, to named hosts, with a cookie jar that may be saved to a file the
  caller names. Nothing in the test suite constructs a request with it.
"""

from __future__ import annotations

import contextlib
import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol

from primarysource.errors import LibError
from primarysource.fetch import Response as StreamResponse
from primarysource.fetch import check_url
from primarysource.settings import require_network

__all__ = [
    "API_HOST",
    "DOWNLOAD_HOST_PREFIX",
    "STORE_HOST",
    "USER_AGENT",
    "HttpRequest",
    "HttpResponse",
    "PoliteTransport",
    "StreamResponse",
    "Transport",
    "UrllibTransport",
    "download_host_allowed",
    "ensure_outside_repository",
]

STORE_HOST = "webstore.iec.ch"
API_HOST = "webstore-search-api.iec.ch"
DOWNLOAD_HOST_PREFIX = "storage-watermark-"
"""The download link the store hands out is a pre-signed S3 URL on `storage-watermark-prd-iec-ch.s3.<region>
.amazonaws.com`. Only a host that starts so and ends `.amazonaws.com` is followed."""
USER_AGENT = "primarysource-iec-client (+https://github.com/b1tninja-labs/primarysource)"
MAX_BODY = 16 * 1024 * 1024
TIMEOUT = 60.0
MIN_INTERVAL = 1.0


@dataclass(frozen=True, slots=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """`headers` has lower-case names."""

    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        """The decoded JSON. The store double-encodes some answers (a JSON string holding JSON); `json_twice`."""
        try:
            return json.loads(self.body)
        except ValueError as error:
            raise LibError("the store answered something that is not JSON", "the site may have changed") from error

    def json_twice(self) -> Any:
        value = self.json()
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError as error:
                raise LibError("the store answered a string that is not JSON", "the site may have changed") from error
        return value


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...

    def open_stream(self, request: HttpRequest) -> AbstractContextManager[StreamResponse]: ...

    def cookie(self, name: str) -> str | None: ...

    def set_cookie(self, name: str, value: str) -> None: ...


def download_host_allowed(host: str | None) -> bool:
    return bool(host) and (host or "").startswith(DOWNLOAD_HOST_PREFIX) and (host or "").endswith(".amazonaws.com")


def ensure_outside_repository(path: Path) -> Path:
    """Refuse a path inside any git working tree: a cookie jar or a download must never be committable."""
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            raise LibError(
                f"{path} is inside a git repository ({parent})",
                "use a directory outside every repository (the collection home, or a path of your own)",
            )
    return resolved


# --- polite wrapper ---------------------------------------------------------------------------------------------


class PoliteTransport:
    """The settings gate, one request per `min_interval` seconds, and the generic User-Agent."""

    def __init__(
        self,
        inner: Transport,
        *,
        min_interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._inner = inner
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._environ = environ
        self._last: float | None = None
        self.requests = 0

    def _begin(self, request: HttpRequest) -> HttpRequest:
        require_network("the IEC webstore", collection="iec", environ=self._environ)
        if self._last is not None:
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1
        headers = {k: v for k, v in request.headers.items() if k.lower() != "user-agent"}
        headers["User-Agent"] = USER_AGENT
        return HttpRequest(request.method, request.url, headers, request.body)

    def send(self, request: HttpRequest) -> HttpResponse:
        return self._inner.send(self._begin(request))

    def open_stream(self, request: HttpRequest) -> AbstractContextManager[StreamResponse]:
        return self._inner.open_stream(self._begin(request))

    def cookie(self, name: str) -> str | None:
        return self._inner.cookie(name)

    def set_cookie(self, name: str, value: str) -> None:
        self._inner.set_cookie(name, value)


# --- urllib default ---------------------------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None


class _Stream:
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
    """https to the named hosts only; cookies kept in a jar, saved to `session_file` when one is given."""

    def __init__(
        self,
        hosts: Sequence[str] = (STORE_HOST, API_HOST),
        *,
        session_file: Path | None = None,
        timeout: float = TIMEOUT,
    ) -> None:
        self._hosts = tuple(hosts)
        self._timeout = timeout
        self._session_file = ensure_outside_repository(session_file) if session_file else None
        self._jar = http.cookiejar.LWPCookieJar()
        if self._session_file and self._session_file.is_file():
            with contextlib.suppress(OSError, http.cookiejar.LoadError):
                self._jar.load(str(self._session_file), ignore_discard=True)
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar), _NoRedirect)

    def _check(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).hostname
        check_url(url, self._hosts + ((host,) if host and download_host_allowed(host) else ()))

    def _open(self, request: HttpRequest) -> Any:
        self._check(request.url)
        raw = urllib.request.Request(  # noqa: S310 - https and the host were checked above
            request.url, data=request.body, headers=dict(request.headers), method=request.method
        )
        try:
            return self._opener.open(raw, timeout=self._timeout)
        except urllib.error.HTTPError as error:
            return error
        except (urllib.error.URLError, OSError) as error:
            raise LibError(f"cannot reach {request.url.split('?')[0]}: {error}", "check the connection") from error

    def send(self, request: HttpRequest) -> HttpResponse:
        response = self._open(request)
        try:
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                raise LibError(f"{request.url.split('?')[0]} answered more than {MAX_BODY} bytes", "refusing it")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return HttpResponse(int(response.status if hasattr(response, "status") else response.code), headers, body)
        finally:
            response.close()
        # the jar is saved by `save_session`, called by the session after a login

    @contextlib.contextmanager
    def open_stream(self, request: HttpRequest) -> Iterator[StreamResponse]:
        response = self._open(request)
        try:
            yield _Stream(int(getattr(response, "status", None) or response.code), response.headers, response)
        finally:
            response.close()

    def cookie(self, name: str) -> str | None:
        for cookie in self._jar:
            if cookie.name == name and cookie.value is not None:
                return cookie.value
        return None

    def set_cookie(self, name: str, value: str) -> None:
        self._jar.set_cookie(
            http.cookiejar.Cookie(
                0, name, value, None, False, STORE_HOST, True, False, "/", True, True, None, True, None, None, {}
            )
        )

    def save_session(self) -> None:
        """Write the cookie jar to the session file (mode 0600 where the OS has one). No file named: no-op."""
        if self._session_file is None:
            return
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        self._jar.save(str(self._session_file), ignore_discard=True)
        with contextlib.suppress(OSError):
            os.chmod(self._session_file, 0o600)
