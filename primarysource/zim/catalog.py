"""The public Kiwix catalogue (OPDS) and verified downloads. The only module that touches the network.

Everything else in zimlore is offline. This module exists because "put ZIM files in a directory" is a poor first
step for someone who does not yet know which file holds Flask's documentation.

Facts measured against the live service on 2026-11-07 and the reason for each rule below:

* `https://library.kiwix.org/catalog/v2/...` answers 301 and the feed lives at `opds.library.kiwix.org`.
* `entries?q=...&lang=eng&count=N` filters; `name=<exact>` returns every dated edition of one name.
* The acquisition link in the feed ends in `.zim.meta4`. The `.meta4` is a Metalink document carrying the
  file's real byte size and its SHA-256, and the `.zim` URL redirects to an arbitrary mirror. So the hash is
  read from the kiwix.org family of hosts (`.meta4` redirects stay inside it too: `download.kiwix.org` answers 301
  to `lb.download.kiwix.org`) and the bytes may come from anywhere: a download is accepted only if it matches.
* The feed's own `length` is rounded (617,472 for a file of 617,313 bytes), so it is never used as a check.

Every hop of every fetch, redirects included, is checked again: https only (plain http only to a local host),
never https down to http, never to a loopback, private or link-local address unless the request began at a local
host. Host names are not resolved, so a public name that points at a private address is not caught here.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import ipaddress
import os
import re
import shutil
import socket
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__, library, manage
from .errors import ZimloreError

CATALOG_URL = "https://opds.library.kiwix.org/catalog/v2/entries"
USER_AGENT = f"zimlore/{__version__}"
ATOM = {"a": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/terms/"}
METALINK = "{urn:ietf:params:xml:ns:metalink}"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
CATALOGUE_DOMAIN = "kiwix.org"
"""The `.meta4` carrying the trusted size and hash is fetched from this domain or a subdomain (redirects included).
Only the `.zim` bytes may come from another mirror."""
STALE_LOCK_SECONDS = 3600
"""A `.part.lock` is touched on every chunk, so one whose last touch is older than this belongs to a process that
died. It is reported with the remedy and never broken silently: deleting a live lock would let two downloads write
one `.part`."""
DOWNLOAD_DEADLINE_SECONDS = 6 * 3600
"""A download that has not finished this long after it started is stopped (the `.part` stays and resumes). The
socket timeout is per read, so without this a mirror sending one byte a minute would hold the lock for ever."""
CHUNK = 1 << 20
"""The read size of a download: also the granularity of the deadline and byte-cap checks."""
PAGE_SIZE = 100
MAX_PAGES = 50

Opener = Callable[[urllib.request.Request], Any]

RETRY = "retry later; installed libraries still work"
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
_FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,190}\.zim")
_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
_BIDI = set("‪‫‬‭‮⁦⁧⁨⁩")


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    title: str
    date: str
    language: str
    summary: str
    creator: str
    articles: int
    approx_bytes: int  # the feed's rounded length: a size estimate, never a check
    url: str  # the .zim URL (the feed's .meta4 link without the suffix)
    tags: tuple[str, ...]


def clean(text: str) -> str:
    """Catalogue text with escape sequences and control or bidi-override characters removed, so a hostile feed
    cannot recolour, overwrite or reorder what a terminal prints."""
    text = _ANSI.sub("", text)
    return "".join(
        " " if ch in "\t\n\r" else ch
        for ch in text
        if ch in "\t\n\r" or (unicodedata.category(ch) != "Cc" and ch not in _BIDI)
    )


def is_catalogue_host(host: str | None) -> bool:
    return bool(host) and (host == CATALOGUE_DOMAIN or str(host).endswith("." + CATALOGUE_DOMAIN))


def _non_public(host: str | None) -> bool:
    """A loopback, private, link-local or otherwise non-global address, in any spelling `inet_aton` accepts."""
    name = (host or "").lower().rstrip(".")
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        try:
            address = ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(name)))
        except OSError:
            return False
    return not address.is_global


def _check_url(url: str, previous: str = "", *, origin_host: str | None = None) -> None:
    """Refuse a URL that is not https (http only to a local host), that downgrades from `previous`, or that points
    at a non-public address when the request did not begin at a local host."""
    parts = urllib.parse.urlsplit(url)
    local = parts.hostname in LOCAL_HOSTS
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ZimloreError(f"refusing to fetch {url}: only https is allowed", "")
    if previous and urllib.parse.urlsplit(previous).scheme == "https" and parts.scheme != "https":
        raise ZimloreError(f"refusing to follow a redirect from {previous} down to {url}: https must stay https", "")
    started_local = (origin_host if origin_host is not None else parts.hostname) in LOCAL_HOSTS
    if _non_public(parts.hostname) and not started_local:
        raise ZimloreError(f"refusing to fetch {url}: it is a loopback, private or link-local address", "")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Re-runs the URL rules on every hop. With `pinned`, a request that did not begin at a local host may only
    be redirected within the catalogue domain (the `.meta4` is the root of trust for the whole download)."""

    def __init__(self, pinned: bool = False) -> None:
        super().__init__()
        self.pinned = pinned

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        origin = req.origin_req_host
        _check_url(newurl, req.full_url, origin_host=origin)
        host = urllib.parse.urlsplit(newurl).hostname
        if self.pinned and origin not in LOCAL_HOSTS and not is_catalogue_host(host):
            raise ZimloreError(
                f"refusing to follow a redirect to {newurl}: the .meta4 must come from {CATALOGUE_DOMAIN}",
                "the size and hash would otherwise come from the host that serves the file",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request: urllib.request.Request, pinned: bool = False) -> Any:
    return urllib.request.build_opener(_Redirects(pinned)).open(request, timeout=60)  # noqa: S310


def whole_number(value: object, what: str, *, default: int | None = None, minimum: int = 0) -> int:
    """A catalogue number as an int. Anything but plain ASCII digits (a sign, a decimal point, `²`, text, a value
    of more than 15 digits) is a `ZimloreError`, never a bare `ValueError`. Missing or empty gives `default` when
    set."""
    text = str(value).strip() if value is not None else ""
    if not text and default is not None:
        return default
    if not (text.isascii() and text.isdigit()) or len(text) > 15:
        raise ZimloreError(f"the catalogue returned {what} {text[:40]!r}, which is not a whole number", RETRY)
    number = int(text)
    if number < minimum:
        raise ZimloreError(f"the catalogue returned {what} {number}, below the minimum {minimum}", RETRY)
    return number


def _fetch_error(what: str, error: BaseException) -> ZimloreError:
    return ZimloreError(f"could not fetch {what}: {error}", "check the network, then " + RETRY)


def _get(url: str, opener: Opener | None = None, limit: int = 20_000_000, *, pinned: bool = False) -> bytes:
    _check_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        with (opener or (lambda r: _open(r, pinned)))(request) as response:
            data: bytes = response.read(limit + 1)
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise _fetch_error(url, error) from error
    if len(data) > limit:
        raise ZimloreError(f"{url} is larger than {limit} bytes; refusing to read it into memory")
    return data


def parse_feed(xml: bytes) -> tuple[list[CatalogEntry], int]:
    """Entries and the feed's `totalResults`. Entries without a ZIM acquisition link are skipped (the catalogue
    also lists non-ZIM resources in principle) and are not counted as results. Text fields are `clean`ed and
    numbers go through `whole_number`."""
    try:
        root = ET.fromstring(xml)  # noqa: S314 - a catalogue feed from kiwix.org; no external entities in expat
    except ET.ParseError as error:
        raise ZimloreError(f"the catalogue did not return valid XML ({error})", "try again later") from error
    total_node = root.find("a:totalResults", ATOM)
    total = whole_number(total_node.text if total_node is not None else None, "totalResults", default=0)
    entries: list[CatalogEntry] = []
    for node in root.findall("a:entry", ATOM):

        def text(tag: str, node: ET.Element = node) -> str:
            found = node.find(f"a:{tag}", ATOM)
            return clean((found.text or "").strip()) if found is not None else ""

        link = next((n for n in node.findall("a:link", ATOM) if n.get("type") == "application/x-zim"), None)
        if link is None or not text("name"):
            continue
        href = link.get("href", "")
        author = node.find("a:author/a:name", ATOM)
        entries.append(
            CatalogEntry(
                name=text("name"),
                title=text("title"),
                date=text("updated")[:10],
                language=text("language"),
                summary=text("summary"),
                creator=clean((author.text or "").strip()) if author is not None else "",
                articles=whole_number(text("articleCount"), "articleCount", default=0),
                approx_bytes=whole_number(link.get("length"), "length", default=0),
                url=href[: -len(".meta4")] if href.endswith(".meta4") else href,
                tags=tuple(t for t in text("tags").split(";") if t and not t.startswith("_")),
            )
        )
    return entries, total


def query(
    text: str = "",
    *,
    name: str = "",
    language: str = "eng",
    count: int = 20,
    start: int = 0,
    tag: str = "",
    max_bytes: int = 0,
    base: str | None = None,
    opener: Opener | None = None,
) -> tuple[list[CatalogEntry], int]:
    base = base or CATALOG_URL  # looked up per call so a test can point the whole module at a local feed
    params = {"count": str(count)}
    if start:
        params["start"] = str(start)
    if text:
        params["q"] = text
    if name:
        params["name"] = name
    if language:
        params["lang"] = language
    if tag:
        params["tag"] = tag  # e.g. "devdocs": 243 ZIMs on 2026-11-07
    if max_bytes > 0:
        params["maxsize"] = str(max_bytes)  # bytes (checked: 140 DevDocs ZIMs are <= 1,000,000)
    return parse_feed(_get(f"{base}?{urllib.parse.urlencode(params)}", opener))


def editions_of(name: str, *, opener: Opener | None = None) -> list[CatalogEntry]:
    """EVERY catalogue edition of one name, paged until the feed's `totalResults` is reached, a page adds nothing
    new, or `MAX_PAGES`. A caller choosing 'the newest' must see all of them:
    the feed's own order is not a promise."""
    found: dict[str, CatalogEntry] = {}
    start = 0
    for _ in range(MAX_PAGES):
        page, total = query(name=name, language="", count=PAGE_SIZE, start=start, opener=opener)
        fresh = [e for e in page if e.url not in found]
        found.update((e.url, e) for e in fresh)
        start += len(page)
        if not fresh or len(found) >= total:
            break
    return list(found.values())


def latest(entries: list[CatalogEntry]) -> list[CatalogEntry]:
    """One entry per name: the newest by parsed date, whatever order `entries` arrive in."""
    newest: dict[str, CatalogEntry] = {}
    for entry in sorted(entries, key=lambda e: library.date_key(e.date), reverse=True):
        newest.setdefault(entry.name, entry)
    return list(newest.values())


@dataclass(frozen=True)
class Metalink:
    size: int
    sha256: str


def parse_metalink(xml: bytes) -> Metalink:
    try:
        root = ET.fromstring(xml)  # noqa: S314
    except ET.ParseError as error:
        raise ZimloreError(f"the .meta4 file is not valid XML ({error})") from error
    for file in root.iter(f"{METALINK}file"):  # size and hash must describe the SAME file element
        size = file.find(f"{METALINK}size")
        digest = next((h for h in file.iter(f"{METALINK}hash") if h.get("type") == "sha-256"), None)
        text = (digest.text or "").strip().lower() if digest is not None else ""
        if size is not None and re.fullmatch(r"[0-9a-f]{64}", text):
            return Metalink(whole_number(size.text, "the .meta4 size", minimum=1), text)
    raise ZimloreError("the .meta4 file carries no size and SHA-256", "the download cannot be verified; not fetching")


def target_name(entry: CatalogEntry) -> str:
    """The file name a download of `entry` gets. It carries the edition date, so a newer edition is a different
    file and an update never touches the older one. Only a plain name is accepted: no separators, no spaces or
    control characters, no Windows device name (`CON.zim` would open the console, not a file)."""
    name = Path(urllib.parse.urlsplit(entry.url).path).name
    if not name.endswith(".zim"):
        raise ZimloreError(f"{entry.url} does not name a .zim file")
    if not _FILE_NAME.fullmatch(name) or name.split(".")[0].upper() in _RESERVED_NAMES:
        raise ZimloreError(
            f"{entry.url} names a file ({name[:60]!r}) that zimlore will not create",
            "ZIM file names are letters, digits and . _ + - and may not be a Windows device name",
        )
    return name


def _touch(path: Path) -> None:
    with contextlib.suppress(OSError):  # a lock that cannot be touched only risks being reported stale
        os.utime(path)


def _acquire_lock(lock: Path, stale_after: float) -> None:
    """Create `lock` exclusively. An existing lock is an error either way: a young one means another download is
    writing the same `.part`; an old one is reported as probably stale, with the remedy, but never removed here."""
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0.0
        if age > stale_after:
            raise ZimloreError(
                f"{lock} is {age / 60:.0f} minutes old: a download that died probably left it behind",
                f"if no zimlore is running, delete {lock} and run the same command again; the .part resumes",
            ) from None
        raise ZimloreError(
            f"another zimlore is downloading to {lock.with_suffix('').name} (lock {lock})",
            "wait for it to finish; two downloads must not write one .part",
        ) from None
    with os.fdopen(descriptor, "w") as handle:
        handle.write(f"pid {os.getpid()}\n")


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    return headers.get(name) if headers is not None else None


def _range_start(response: Any) -> int | None:
    match = re.fullmatch(r"bytes (\d+)-\d+/(?:\d+|\*)", _header(response, "Content-Range") or "", re.ASCII)
    return int(match.group(1)) if match else None


def _transfer(
    entry: CatalogEntry,
    part: Path,
    lock: Path,
    meta: Metalink,
    opener: Opener | None,
    progress: Callable[[int, int], None] | None,
    deadline: float = DOWNLOAD_DEADLINE_SECONDS,
) -> tuple[int, str]:
    """Bring `part` to `meta.size` bytes and return (bytes, SHA-256 of the WHOLE file). An existing `.part` is
    resumed with a Range request after its prefix is re-hashed; a mirror that refuses the range (200 instead of
    206, a wrong Content-Range, 416) makes the download start over from byte zero, never splice. Never more than
    `meta.size` bytes reach the disk, and no more than `deadline` seconds are spent."""
    started = time.monotonic()
    for _ in range(2):
        digest = hashlib.sha256()
        offset = part.stat().st_size if part.exists() else 0
        if offset > meta.size:  # longer than the file can be: not a prefix of it
            part.unlink()
            offset = 0
        if offset:
            with part.open("rb") as prefix:
                while chunk := prefix.read(1 << 20):
                    digest.update(chunk)
                    _touch(lock)
            if progress:
                progress(offset, meta.size)
        if offset == meta.size:
            return offset, digest.hexdigest()  # a complete .part: nothing to fetch, the hash check decides
        headers = {"User-Agent": USER_AGENT}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(entry.url, headers=headers)  # noqa: S310
        try:
            reply = (opener or _open)(request)
        except urllib.error.HTTPError as error:
            if error.code == 416 and offset:  # the mirror's file is shorter than our part
                part.unlink(missing_ok=True)
                continue
            raise ZimloreError(f"download of {entry.name} failed ({error})", RETRY) from error
        except (OSError, http.client.HTTPException, ValueError) as error:
            raise ZimloreError(f"download of {entry.name} failed ({error})", RETRY) from error
        with reply as response:
            status = getattr(response, "status", 200)
            if offset and not (status == 206 and _range_start(response) == offset):
                part.unlink(missing_ok=True)
                if status != 200:
                    continue
                digest, offset = hashlib.sha256(), 0  # Range refused: this 200 is the whole file, use it from zero
            announced = _header(response, "Content-Length")
            promised = int(announced) if announced and announced.isascii() and announced.isdigit() else None
            if promised is not None and promised > meta.size - offset:
                part.unlink(missing_ok=True)
                raise ZimloreError(
                    f"{entry.name}: the server announces {promised} bytes; the .meta4 allows {meta.size - offset}",
                    "the mirror is serving a different file; nothing was kept",
                )
            done = offset
            too_much = False
            try:
                with part.open("ab" if offset else "wb") as out:
                    while chunk := response.read(min(CHUNK, meta.size - done + 1)):
                        if done + len(chunk) > meta.size:
                            too_much = True
                            break
                        out.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        _touch(lock)
                        if progress:
                            progress(done, meta.size)
                        if done < meta.size and time.monotonic() - started >= deadline:
                            raise ZimloreError(
                                f"download of {entry.name} passed its {deadline:.0f} s deadline at {done} of "
                                f"{meta.size} bytes",
                                f"run the same command again: it resumes from {part}",
                            )
            except (OSError, http.client.HTTPException, ValueError) as error:
                raise ZimloreError(
                    f"download of {entry.name} was interrupted at {done} of {meta.size} bytes ({error})",
                    f"run the same command again: it resumes from {part}",
                ) from error
            if too_much:
                part.unlink(missing_ok=True)
                raise ZimloreError(
                    f"{entry.name}: the server sent more than the {meta.size} bytes the .meta4 allows; discarded",
                    "the mirror is serving a different file",
                )
            if promised is not None and done - offset < promised:
                raise ZimloreError(
                    f"download of {entry.name} was cut off at {done} of {meta.size} bytes",
                    f"run the same command again: it resumes from {part}",
                )
            return done, digest.hexdigest()
    raise ZimloreError(f"the mirror for {entry.name} kept refusing to serve the file", RETRY)


@dataclass(frozen=True)
class Downloaded:
    path: Path
    status: str  # "installed" | "replaced" | "already-installed"


def _ensure_replaceable(final: Path) -> None:
    """Fail BEFORE any download when `final` cannot be replaced. On Windows libzim (or any reader) holds a ZIM
    without share-delete, so the file cannot be renamed or replaced until the last handle is gone: probe with a
    rename and put it back."""
    library.close_path(final)
    probe = final.with_name(final.name + ".probe")
    try:
        os.rename(final, probe)
    except OSError as error:
        raise ZimloreError(
            f"{final} is in use by another process and cannot be replaced ({error}); nothing was downloaded",
            "stop any running 'primarysource zim mcp' server or kiwix reader that has it open, "
            "then run the same command again",
        ) from error
    try:
        os.rename(probe, final)
    except OSError as error:  # should be impossible: we just renamed it
        raise ZimloreError(
            f"{final} was moved to {probe} and could not be moved back ({error})", f"rename {probe}"
        ) from error


def _same_file(final: Path, meta: Metalink) -> bool:
    record, _ = manage.read_sidecar(final)
    return bool(record and final.is_file() and record.sha256 == meta.sha256 and final.stat().st_size == meta.size)


def _check_space(directory: Path, part: Path, meta: Metalink, name: str) -> None:
    need = meta.size - (part.stat().st_size if part.exists() else 0)
    try:
        free = shutil.disk_usage(directory).free
    except OSError:
        return
    if need > free:
        raise ZimloreError(
            f"{name} needs {need} more bytes and {directory} has {free} free; nothing was downloaded",
            "free space: primarysource zim du shows the use, primarysource zim prune --yes drops old editions",
        )


def download(
    entry: CatalogEntry,
    directory: Path,
    *,
    opener: Opener | None = None,
    progress: Callable[[int, int], None] | None = None,
    added_by: str = "get",
    stale_lock_seconds: float = STALE_LOCK_SECONDS,
    replace: bool = False,
    deadline_seconds: float = DOWNLOAD_DEADLINE_SECONDS,
) -> Path:
    """`download_result(...).path`: see there."""
    return download_result(
        entry,
        directory,
        opener=opener,
        progress=progress,
        added_by=added_by,
        stale_lock_seconds=stale_lock_seconds,
        replace=replace,
        deadline_seconds=deadline_seconds,
    ).path


def download_result(
    entry: CatalogEntry,
    directory: Path,
    *,
    opener: Opener | None = None,
    progress: Callable[[int, int], None] | None = None,
    added_by: str = "get",
    stale_lock_seconds: float = STALE_LOCK_SECONDS,
    replace: bool = False,
    deadline_seconds: float = DOWNLOAD_DEADLINE_SECONDS,
) -> Downloaded:
    """Fetch `entry` into `directory`, verifying size and SHA-256 against the `.meta4` before the file takes its
    final name. A failed or interrupted download leaves a `.part` file, never a `.zim` that looks complete, and
    the next call resumes it. The size cap comes from the `.meta4` before the first byte, a refusal to exceed the
    free disk space too, and a `.part.lock` keeps two downloads from writing one `.part`.

    An existing file of that name is never replaced unless `replace`: if its sidecar already records this
    `.meta4`'s SHA-256 (and its size matches) the call is a no-op returning `already-installed`. With `replace`
    on Windows a file that is open elsewhere is reported before the download starts."""
    final = directory / target_name(entry)
    _check_url(entry.url)
    host = urllib.parse.urlsplit(entry.url).hostname
    if not (is_catalogue_host(host) or host in LOCAL_HOSTS):
        raise ZimloreError(
            f"{entry.url} is not on {CATALOGUE_DOMAIN}; its .meta4 would come from the host that serves the file",
            "zimlore downloads only catalogue entries; to install a file from elsewhere use primarysource zim add",
        )
    directory.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + ".part")
    lock = part.with_name(part.name + ".lock")
    _acquire_lock(lock, stale_lock_seconds)
    try:
        existing = os.path.lexists(final)
        if existing and replace:
            _ensure_replaceable(final)
        meta = parse_metalink(_get(entry.url + ".meta4", opener, pinned=True))
        if existing:
            if _same_file(final, meta):
                return Downloaded(final, "already-installed")
            if not replace:
                raise ZimloreError(
                    f"{final} already exists and is not the file the catalogue describes; not replacing it",
                    "primarysource zim get NAME --replace replaces it (the old file is lost); "
                    "otherwise move it aside",
                )
        _check_space(directory, part, meta, entry.name)
        done, hexdigest = _transfer(entry, part, lock, meta, opener, progress, deadline_seconds)
        if done != meta.size or hexdigest != meta.sha256:
            part.unlink(missing_ok=True)
            raise ZimloreError(
                f"{entry.name}: downloaded {done} bytes with sha256 {hexdigest[:12]}…, expected "
                f"{meta.size} bytes with {meta.sha256[:12]}…; the file was discarded",
                "retry; if it persists the mirror is serving a different file",
            )
        if existing:
            library.close_path(final)
        try:
            os.replace(part, final)
        except OSError as error:
            raise ZimloreError(
                f"the verified download of {entry.name} could not be installed as {final} ({error})",
                f"it is kept as {part}; free the target and run the same command again (no re-download is needed)",
            ) from error
    finally:
        lock.unlink(missing_ok=True)
    record = manage.Provenance(entry.url, entry.name, entry.date, meta.sha256, meta.size, manage.now(), added_by)
    try:
        manage.write_sidecar(final, record)
    except OSError as error:
        manage.sidecar_path(final).unlink(missing_ok=True)  # never leave the previous file's record on this one
        raise ZimloreError(
            f"{final} was installed and verified but its provenance record could not be written ({error})",
            "free disk space, then primarysource zim verify --adopt records what the file is",
        ) from error
    return Downloaded(final, "replaced" if existing else "installed")
