"""A pinned source archive, streamed: verified, bounded, never extracted to disk.

`fetch_tree` opens a gzip or plain tar over HTTPS (or `read_tree` takes any binary stream, which is how a local
file and a test's in-memory archive come in), walks the members in stream mode with `tarfile` mode `r|`, and keeps
only the regular files `include` accepts, in memory.

What is pinned is **the selected files**, not the archive: `manifest_digest` is the sha256 of one line per kept
file, `<sha256 of its bytes>  <path>`, sorted by path. It is checked before anything is returned, so a damaged,
truncated or substituted archive yields nothing. It is independent of how the archive was made, which matters:
a forge tarball, a `git archive` and a gitiles subtree archive of the same commit are three different byte
streams (gitiles stamps each header with the time of the request, so its tar differs from one fetch to the next,
measured), and the same selected files give the same manifest from all three. The digests of the `.tar` and the
`.gz` are reported but are not what a pin means.

Bounds, each a `LibError` naming what to do:

- compressed bytes, decompressed bytes (a gzip bomb), member count, bytes per kept member, bytes in all;
- a kept member whose header declares more than the per-member bound is refused before its data is read;
- links, devices and directories are skipped; a member name that is absolute, has a `..` part, a NUL or a
  backslash is skipped and counted, never joined to a path;
- a redirect only to a host the source lists;
- one request per second (`Throttle`), whichever source is tried.

This is the interim form of the proposed core function `cl.fetch_git_tree_pinned`. Two things it would take from
sibling projects rather than own: from `archivekit` (D:\\code\\archivekit) the bounded stream reader for tar and
gzip members and its safe-name rules; from `gitobj` (D:\\code\\gitobj) a git tree hash, so a pin can name the
tree object (`git rev-parse <commit>^{tree}`) and the digest of the files read can be checked against it, which
holds whichever server or compression produced the bytes.
"""

from __future__ import annotations

import gzip
import hashlib
import http.client
import io
import re
import tarfile
import time
import urllib.error
import urllib.request
import zlib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import IO, Any, Protocol
from urllib.parse import urlsplit

from primarysource import __version__
from primarysource.errors import LibError

MIN_INTERVAL = 1.0
_CHUNK = 1 << 20
_USER_AGENT = f"primarysource/{__version__} (pinned archive reader)"


class Refused(LibError):
    """A failure that no other source can cure: a digest that is not the pin, a bound exceeded, an unlisted
    redirect. `fetch_tree` raises it at once instead of trying the next mirror."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where a tree can be fetched. `strip` leading path components are removed from member names (1 for a
    forge tarball's top directory, 0 for a subtree archive). With `subdir`,
    only members below it are read and the prefix is removed, so one tree spec serves a whole-repository tarball
    and a subtree archive alike. `hosts` are the hosts a redirect may lead to, besides the URL's own."""

    url: str
    strip: int = 1
    hosts: tuple[str, ...] = ()
    subdir: str = ""


@dataclass(frozen=True, slots=True)
class Limits:
    """Ceilings on what a fetch will accept."""

    compressed_bytes: int = 150_000_000
    tar_bytes: int = 800_000_000
    members: int = 100_000
    member_bytes: int = 8_000_000
    total_bytes: int = 400_000_000


@dataclass(frozen=True, slots=True)
class Fetched:
    """The kept files and what was measured while reading them."""

    files: dict[str, bytes]
    files_sha256: str
    tar_sha256: str
    gz_sha256: str | None
    members: int
    tar_bytes: int
    kept_bytes: int
    skipped: dict[str, int] = field(default_factory=dict)
    url: str = ""
    pinned: bool = True


class Throttle:
    """At most one call per `interval` seconds; the clock and the sleep are injectable for tests."""

    def __init__(
        self,
        interval: float = MIN_INTERVAL,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self.interval:
            self._sleep(self.interval - (now - self._last))
            now = self._clock()
        self._last = now


DEFAULT_THROTTLE = Throttle()


class _Reader(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class _Counting:
    """Wraps a stream: counts and hashes what passes through and stops at a ceiling."""

    def __init__(self, stream: _Reader, ceiling: int, what: str, hint: str) -> None:
        self._stream = stream
        self._ceiling = ceiling
        self._what = what
        self._hint = hint
        self.count = 0
        self.tail = b""
        self.digest = hashlib.sha256()

    def read(self, size: int = -1, /) -> bytes:
        chunk = self._stream.read(size if size > 0 else _CHUNK)
        self.count += len(chunk)
        if self.count > self._ceiling:
            raise Refused(
                f"{self._what} is over {self._ceiling:,} bytes; this is not the expected archive", self._hint
            )
        self.digest.update(chunk)
        self.tail = (self.tail + chunk)[-1024:]
        return chunk


class _Prefixed:
    """A stream with some bytes already read from it put back in front."""

    def __init__(self, prefix: bytes, stream: _Reader) -> None:
        self._prefix = prefix
        self._stream = stream

    def read(self, size: int = -1, /) -> bytes:
        if not self._prefix:
            return self._stream.read(size)
        if size < 0:
            head, self._prefix = self._prefix, b""
            return head + self._stream.read()
        head, self._prefix = self._prefix[:size], self._prefix[size:]
        if len(head) < size:
            head += self._stream.read(size - len(head))
        return head


def _safe_name(name: str, strip: int, subdir: str = "") -> str | None:
    """The member's path inside the tree, or None when it is unsafe; an empty string when it is not below the
    stripped prefix (or `subdir`)."""
    if "\x00" in name or "\\" in name or name.startswith("/") or re.match(r"[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None
    if len(parts) <= strip:
        return ""
    inside = parts[strip:]
    if subdir:
        head = [p for p in subdir.split("/") if p]
        if inside[: len(head)] != head or len(inside) == len(head):
            return ""
        inside = inside[len(head) :]
    return "/".join(inside)


def manifest_digest(files: Mapping[str, bytes]) -> str:
    """The pin of a set of files: sha256 over `<sha256 of the bytes>  <path>` lines, sorted by path."""
    lines = "".join(f"{hashlib.sha256(files[path]).hexdigest()}  {path}\n" for path in sorted(files))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def read_tree(
    stream: _Reader,
    source: Source,
    *,
    include: Callable[[str], bool],
    expect: str | None = None,
    limits: Limits | None = None,
) -> Fetched:
    """Walk one archive stream. Raises `LibError` for a manifest digest that is not `expect` (when given), a bound
    exceeded, or an archive that is truncated or damaged; returns nothing partial."""
    limits = limits or Limits()
    remedy = "fetch the archive again; if it keeps failing, the pin in the catalogue is wrong or the source changed"
    raw = _Counting(stream, limits.compressed_bytes, "the archive", remedy)
    magic = raw.read(2)
    gz = magic == b"\x1f\x8b"
    prefixed: Any = _Prefixed(magic, raw)
    plain: Any = gzip.GzipFile(fileobj=prefixed, mode="rb") if gz else prefixed
    tar_stream = _Counting(plain, limits.tar_bytes, "the decompressed archive", remedy)
    files: dict[str, bytes] = {}
    skipped: Counter[str] = Counter()
    kept = 0
    members = 0
    try:
        with tarfile.open(fileobj=tar_stream, mode="r|") as tar:  # type: ignore[call-overload]
            for member in tar:
                members += 1
                if members > limits.members:
                    raise Refused(f"the archive has more than {limits.members:,} members", remedy)
                if not member.isreg():
                    skipped["link, directory or special file"] += 1
                    continue
                name = _safe_name(member.name, source.strip, source.subdir)
                if name is None:
                    skipped["unsafe member name"] += 1
                    continue
                if not name or not include(name):
                    skipped["not selected"] += 1
                    continue
                if member.size > limits.member_bytes:
                    raise Refused(
                        f"refusing {member.name!r}: it declares {member.size:,} bytes, over the "
                        f"{limits.member_bytes:,} "
                        "limit per file",
                        remedy,
                    )
                handle = tar.extractfile(member)
                data = handle.read(limits.member_bytes + 1) if handle is not None else b""
                if len(data) > limits.member_bytes:
                    raise Refused(f"refusing {member.name!r}: over the per-file limit", remedy)
                kept += len(data)
                if kept > limits.total_bytes:
                    raise Refused(f"the selected files total more than {limits.total_bytes:,} bytes", remedy)
                files[name] = data
        while tar_stream.read(_CHUNK):  # the trailing padding, and the gzip trailer's CRC check
            pass
        # tarfile treats a header cut short as the end of the archive, so check the end marker ourselves:
        # a whole number of 512-byte blocks whose last block is zero
        if tar_stream.count % 512 or tar_stream.tail[-512:] != bytes(512):
            raise LibError("the archive is truncated (it does not end with the tar end-of-archive marker)", remedy)
    except Refused:
        raise
    except (tarfile.TarError, EOFError, gzip.BadGzipFile, zlib.error, http.client.HTTPException, OSError) as exc:
        raise LibError(f"the archive is truncated or damaged ({type(exc).__name__}: {exc})", remedy) from exc
    digest = manifest_digest(files)
    if expect is not None and digest != expect:
        raise Refused(
            f"the selected files have manifest sha256 {digest}, not the {expect} pinned for them",
            "the commit is not the pinned one, the source changed, or the pin is wrong; check the commit, then "
            "update the catalogue's pin",
        )
    return Fetched(
        files=files,
        files_sha256=digest,
        tar_sha256=tar_stream.digest.hexdigest(),
        gz_sha256=raw.digest.hexdigest() if gz else None,
        members=members,
        tar_bytes=tar_stream.count,
        kept_bytes=kept,
        skipped=dict(skipped),
        url=source.url,
        pinned=expect is not None,
    )


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts: frozenset[str]) -> None:
        self._hosts = hosts

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        target = urlsplit(newurl)
        if target.scheme != "https" or (target.hostname or "") not in self._hosts:
            raise Refused(
                f"refusing a redirect to {newurl!r}: its host is not one the catalogue lists for this source",
                "add the host to the source's `hosts` only after checking it is the forge's own download host",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


Opener = Callable[[urllib.request.Request], IO[bytes]]


def _default_opener(source: Source) -> Opener:
    hosts = frozenset({urlsplit(source.url).hostname or "", *source.hosts})
    return urllib.request.build_opener(_Redirects(hosts)).open


def fetch_tree(
    sources: Sequence[Source],
    *,
    include: Callable[[str], bool],
    expect: str | None = None,
    limits: Limits | None = None,
    opener: Opener | None = None,
    throttle: Throttle | None = None,
    timeout: float = 60.0,
) -> Fetched:
    """Try each source in order; the first that reads and verifies wins. A digest mismatch is raised at once and
    does not fall through to the next mirror (a mirror that disagrees is a finding, not a retry)."""
    if not sources:
        raise LibError("no source is listed for this edition", "add one to the catalogue")
    wait = throttle or DEFAULT_THROTTLE
    failures: list[str] = []
    for source in sources:
        if not source.url.startswith("https://"):
            raise Refused(f"refusing {source.url!r}: only https sources are read", "")
        wait.wait()
        request = urllib.request.Request(source.url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
        try:
            handle = (opener or _default_opener(source))(request)
            with handle:
                return read_tree(handle, source, include=include, expect=expect, limits=limits)
        except Refused:
            raise
        except LibError as exc:
            failures.append(f"{source.url}: {exc.message}")
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            failures.append(f"{source.url}: {exc}")
    raise LibError(
        "no source could be read:\n  " + "\n  ".join(failures), "check the network, or pass a downloaded archive"
    )


def read_local(
    path: str,
    source: Source,
    *,
    include: Callable[[str], bool],
    expect: str | None = None,
    limits: Limits | None = None,
) -> Fetched:
    """The same walk over a file the user downloaded."""
    try:
        with open(path, "rb") as stream:  # noqa: PTH123
            return read_tree(io.BufferedReader(stream), source, include=include, expect=expect, limits=limits)
    except FileNotFoundError as exc:
        raise LibError(
            f"no file at {path}", "download the archive first, or omit --archive to fetch the pinned one"
        ) from exc
