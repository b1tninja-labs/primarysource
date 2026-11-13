"""Fetch registry XML from iana.org into `$PRIMARYSOURCE_HOME/iana/`.

Polite by construction: at most one request per `interval` seconds (never under 1.0), an identifying User-Agent,
conditional requests (`If-Modified-Since`) so an unchanged file costs a 304, no redirects followed, only
`https://www.iana.org/assignments/<name>/<name>.xml`, and a response size ceiling. Each file is parsed with the
hardened reader and its root id checked against the name before anything is written; the bytes are stored
exactly as served, atomically, and `manifest.json` records sha256, size and the registry's `updated` date.

The transport is a parameter, so tests inject one; the default uses `urllib`.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import atomic_write
from primarysource.iana import xmlsafe
from primarysource.iana.catalogue import BASE, ENTRIES, url_for
from primarysource.iana.model import from_tree
from primarysource.iana.store import MANIFEST, MAX_BYTES, home, read_manifest

USER_AGENT = "primarysource-iana/0.1 (local registry mirror; at most 1 request per second)"
MIN_INTERVAL = 1.0


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str]], Response]
"""`transport(url, request_headers) -> Response`. It must not follow redirects and must bound the body."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def urllib_transport(url: str, headers: Mapping[str, str]) -> Response:
    """The default transport: one GET, https to www.iana.org only, no redirects, body capped at MAX_BYTES."""
    if not url.startswith(BASE):
        raise LibError(f"refusing to fetch {url!r}", f"only {BASE}<name>/<name>.xml is fetched")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=dict(headers))  # noqa: S310 - the https prefix is checked above
    try:
        with opener.open(request, timeout=60) as reply:
            body = reply.read(MAX_BYTES + 1)
            return Response(reply.status, {k.lower(): v for k, v in reply.headers.items()}, body)
    except urllib.error.HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, b"")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LibError(f"could not reach {url}: {exc}", "check the network and try again") from exc


@dataclass(frozen=True, slots=True)
class Outcome:
    name: str
    status: str
    """`fetched`, `unchanged` (HTTP 304) or `identical` (HTTP 200 with the sha256 already held)."""
    sha256: str
    size: int
    updated: str
    path: Path


@dataclass(slots=True)
class Report:
    outcomes: list[Outcome] = field(default_factory=list)


def catalogue_names() -> list[str]:
    return [e.name for e in ENTRIES]


def import_registries(
    names: Sequence[str],
    *,
    base: Path | None = None,
    transport: Transport | None = None,
    interval: float = MIN_INTERVAL,
    force: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    user_agent: str = USER_AGENT,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Report:
    """Fetch each named registry file. The first failure stops the run and leaves earlier files in place."""
    if os.environ.get("PRIMARYSOURCE_READONLY"):
        raise LibError("the library is read-only (PRIMARYSOURCE_READONLY is set), so nothing is fetched", "unset it")
    if interval < MIN_INTERVAL:
        raise LibError(f"an interval under {MIN_INTERVAL:g} second is refused", "registries are fetched politely")
    wanted = list(dict.fromkeys(names))
    if not wanted:
        raise LibError("no registry named", "name one, e.g. dns-parameters, or use --all for the catalogue")
    urls = {name: url_for(name) for name in wanted}  # validates every spelling before the first request
    send: Transport = transport or urllib_transport
    root = base or home()
    root.mkdir(parents=True, exist_ok=True)
    files = read_manifest(root)
    report = Report()
    last: float | None = None
    for name in wanted:
        if last is not None:
            wait = interval - (clock() - last)
            if wait > 0:
                sleep(wait)
        url = urls[name]
        headers = {"User-Agent": user_agent, "Accept": "application/xml"}
        previous = files.get(name, {})
        target = root / f"{name}.xml"
        if not force and target.is_file() and previous.get("last_modified"):
            headers["If-Modified-Since"] = str(previous["last_modified"])
        last = clock()
        reply = send(url, headers)
        if reply.status == 304 and target.is_file() and previous:
            size = int(previous.get("size", 0))
            report.outcomes.append(
                Outcome(
                    name, "unchanged", str(previous.get("sha256", "")), size, str(previous.get("updated", "")), target
                )
            )
            continue
        if reply.status != 200:
            raise LibError(
                f"{url} answered HTTP {reply.status}", "check the name against https://www.iana.org/protocols"
            )
        if len(reply.body) > MAX_BYTES:
            raise LibError(f"{url} is over {MAX_BYTES:,} bytes", "this is not the expected registry file")
        parsed = from_tree(xmlsafe.parse(reply.body, MAX_BYTES), name)
        digest = hashlib.sha256(reply.body).hexdigest()
        status = "identical" if target.is_file() and previous.get("sha256") == digest else "fetched"
        atomic_write(target, reply.body)
        files[name] = {
            "url": url,
            "sha256": digest,
            "size": len(reply.body),
            "updated": parsed.updated,
            "fetched": now().isoformat(timespec="seconds"),
            "last_modified": {k.lower(): v for k, v in reply.headers.items()}.get("last-modified", ""),
        }
        manifest = json.dumps({"schema": 1, "files": files}, indent=2, sort_keys=True) + "\n"
        atomic_write(root / MANIFEST, manifest.encode("utf-8"))
        report.outcomes.append(Outcome(name, status, digest, len(reply.body), parsed.updated, target))
    return report
