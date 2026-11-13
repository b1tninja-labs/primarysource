"""Fetch the USB ID database (`usb.ids`) into `$PRIMARYSOURCE_HOME/usbids/`.

Polite by construction: one file, at most one request per `interval` seconds (never under 1.0) across the source
list, an identifying User-Agent, conditional requests (`If-None-Match`, `If-Modified-Since`) so an unchanged file
costs a 304, no redirects followed, https only and only the hosts in `SOURCES`, and a body ceiling.

The file changes daily, so a pin cannot be a promise about the future. `PIN` is the snapshot this code was
developed against. A body whose sha256 is the pinned one installs. A body that is a different snapshot installs
only on `--latest` (or `--sha256 <digest>` naming it), and a body that claims the pinned version with other bytes
is refused as damaged. The parse is checked before anything is written: no entries, or any unplaceable line,
refuses the import. The bytes are stored exactly as served, atomically; `manifest.json` records the digest.

The transport is a parameter, so tests inject one; the default uses `urllib`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import atomic_write
from primarysource.usbids import store
from primarysource.usbids.parse import Limits, parse

USER_AGENT = "primarysource-usbids/0.1 (local usb.ids mirror; at most 1 request per second)"
MIN_INTERVAL = 1.0
MAX_BYTES = 8_000_000


@dataclass(frozen=True, slots=True)
class Pin:
    """One snapshot of `usb.ids`: its `# Version:`, `# Date:`, size and sha256."""

    version: str
    date: str
    size: int
    sha256: str


PIN = Pin(
    version="2026.06.26",
    date="2026-06-26 20:34:02",
    size=730_605,
    sha256="f5a48b0cc8dae1607c2f0bae6b8dc13f2ecef69dbeaeaf34b4be8e280d34dba4",
)
"""Measured 2026-11-13 from both sources below; their bytes had the same length and Last-Modified."""

SOURCES = (
    "https://usb-ids.gowdy.us/usb.ids",
    "https://raw.githubusercontent.com/usbids/usbids/master/usb.ids",
)
"""The maintainer's host (the one linux-usb.org's page points users at), then the GitHub mirror. `www.linux-usb.org`
is not used: its https certificate is for sf.net (hostname mismatch) and its plain http would leave the sha256 as
the only integrity check."""


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
    """The default transport: one GET to a listed https source, no redirects, body capped at MAX_BYTES."""
    if url not in SOURCES:
        raise LibError(f"refusing to fetch {url!r}", "only the sources in primarysource.usbids.importer.SOURCES")
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=dict(headers))  # noqa: S310 - url is one of SOURCES (https)
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
    status: str
    """`fetched`, `unchanged` (HTTP 304), `identical` (HTTP 200, the sha256 already held)."""
    url: str
    sha256: str
    size: int
    version: str
    date: str
    pinned: bool
    path: Path
    counts: dict[str, int]
    requests: int


def import_usbids(
    *,
    base: Path | None = None,
    transport: Transport = urllib_transport,
    sources: Sequence[str] = SOURCES,
    pin: Pin = PIN,
    latest: bool = False,
    sha256: str | None = None,
    force: bool = False,
    interval: float = MIN_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Outcome:
    """Fetch `usb.ids` from the first source that answers 200 (or 304), check it, install it.

    `latest` accepts a snapshot other than the pinned one; `sha256` accepts exactly the named one; `force` skips
    the conditional request and replaces a file whose digest disagrees with its manifest.
    """
    if os.environ.get("PRIMARYSOURCE_READONLY"):
        raise LibError("the library is read-only (PRIMARYSOURCE_READONLY is set), so nothing is fetched", "unset it")
    if interval < MIN_INTERVAL:
        raise LibError(f"an interval under {MIN_INTERVAL:g} second is refused", "the sources are fetched politely")
    expected = sha256.lower() if sha256 else None
    if expected is not None and len(expected) != 64:
        raise LibError(f"{sha256!r} is not a sha256 hex digest", "")
    for url in sources:
        if not url.startswith("https://"):
            raise LibError(f"refusing source {url!r}: https only", "")
    root = base or store.home()
    target = root / store.FILE
    previous = store.read_manifest(root)
    requests = 0
    last: float | None = None
    failures: list[str] = []
    for url in sources:
        if last is not None:
            wait = interval - (clock() - last)
            if wait > 0:
                sleep(wait)
        headers = {"User-Agent": USER_AGENT, "Accept": "text/plain"}
        if not force and target.is_file() and previous.get("url") == url:
            if previous.get("etag"):
                headers["If-None-Match"] = str(previous["etag"])
            if previous.get("last_modified"):
                headers["If-Modified-Since"] = str(previous["last_modified"])
        last = clock()
        requests += 1
        try:
            reply = transport(url, headers)
        except LibError as exc:
            failures.append(exc.message)
            continue
        if reply.status == 304 and target.is_file() and previous:
            held = store.load(root)
            size = int(previous.get("size") or 0)
            return Outcome(
                "unchanged",
                url,
                held.sha256,
                size,
                held.ids.version,
                held.ids.date,
                bool(previous.get("pinned")),
                held.path,
                held.ids.counts(),
                requests,
            )
        if reply.status != 200:
            failures.append(f"{url} answered HTTP {reply.status}")
            continue
        if len(reply.body) > MAX_BYTES:
            failures.append(f"{url} is over {MAX_BYTES:,} bytes")
            continue
        return _install(reply, url, root, previous, pin, latest, expected, requests, now)
    raise LibError("no source gave usb.ids: " + "; ".join(failures), "check the network and try again")


def _install(
    reply: Response,
    url: str,
    root: Path,
    previous: Mapping[str, object],
    pin: Pin,
    latest: bool,
    expected: str | None,
    requests: int,
    now: Callable[[], datetime],
) -> Outcome:
    digest = hashlib.sha256(reply.body).hexdigest()
    ids = parse(reply.body, Limits(data_bytes=MAX_BYTES))
    if not ids.entries:
        raise LibError(f"{url} did not give a usb.ids file (no entries parsed)", "this is not the expected file")
    if ids.problem_count:
        first = ids.problems[0]
        raise LibError(
            f"{url}: {ids.problem_count} line(s) are not usb.ids syntax (first: line {first.line}, {first.reason})",
            "nothing was written; report the line or parse a copy with primarysource.usbids.parse",
        )
    pinned = digest == pin.sha256
    if expected is not None:
        if digest != expected:
            raise LibError(f"{url} has sha256 {digest}, not the {expected} you named", "nothing was written")
    elif not pinned:
        if ids.version == pin.version:
            raise LibError(
                f"{url} claims version {pin.version} but has sha256 {digest}, not the pinned {pin.sha256}: "
                "the file is damaged or altered",
                "nothing was written",
            )
        if not latest:
            raise LibError(
                f"{url} serves snapshot {ids.version or '(no version)'} with sha256 {digest}; the pin is "
                f"{pin.version} ({pin.sha256})",
                "check the digest, then re-run with --latest (or --sha256 <digest>) to install this snapshot",
            )
    target = root / store.FILE
    status = "identical" if target.is_file() and previous.get("sha256") == digest else "fetched"
    atomic_write(target, reply.body)
    record = {
        "url": url,
        "sha256": digest,
        "size": len(reply.body),
        "version": ids.version,
        "date": ids.date,
        "fetched": now().isoformat(timespec="seconds"),
        "etag": reply.headers.get("etag", ""),
        "last_modified": reply.headers.get("last-modified", ""),
        "pinned": pinned,
        "licence": store.LICENCE,
        "counts": ids.counts(),
    }
    atomic_write(root / store.MANIFEST, (json.dumps({"schema": 1, "file": record}, indent=2) + "\n").encode("utf-8"))
    return Outcome(
        status, url, digest, len(reply.body), ids.version, ids.date, pinned, target, ids.counts(), requests
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="primarysource usbids import", description="fetch usb.ids (one request)")
    parser.add_argument("--latest", action="store_true", help="accept a snapshot other than the pinned one")
    parser.add_argument("--sha256", help="accept exactly the snapshot with this digest")
    parser.add_argument("--force", action="store_true", help="unconditional fetch; replace a file that changed")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        out = import_usbids(latest=args.latest, sha256=args.sha256, force=args.force)
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
    print(f"{out.status}: {out.path}")
    print(f"version {out.version}, date {out.date}, {out.size:,} bytes, sha256 {out.sha256}")
    print(f"source {out.url}; pinned snapshot: {'yes' if out.pinned else 'no'}")
    print(", ".join(f"{n:,} {k}" for k, n in out.counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
