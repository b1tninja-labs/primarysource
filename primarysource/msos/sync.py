"""Download the Open Specifications PDF zips linked from learn.microsoft.com.

The Windows Imaging File Format paper is a separate RTF on the Download Center (`WIM_URL`), not a member of
those zips. `sync_wim` stores it beside them.

The page is fetched from learn.microsoft.com. Its zip link is a fwlink or a download.microsoft.com URL, and the
fwlink redirects through Microsoft's own CDN to the zip. A redirect to any other host is refused. The zip is
stored under the collection home; nothing is unpacked here.
"""

from __future__ import annotations

import hashlib
import re
import sys
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256_file
from primarysource.msos.catalogue import SETS, SpecSet
from primarysource.settings import require_network

ZIPS = "zips"
WIM_ID = "wim"
WIM_DOC = "ms-wim"
WIM_PAGE = "https://www.microsoft.com/en-us/download/details.aspx?id=13096"
WIM_URL = (
    "https://download.microsoft.com/download/f/e/f/"
    "fefdc36e-392d-4678-9e4e-771ffa2692ab/Windows%20Imaging%20File%20Format.rtf"
)
WIM_NAME = "Windows Imaging File Format.rtf"
MAX_PAGE = 2 * 1024 * 1024
MAX_ZIP = 2_000_000_000
_UA = "primarysource msos"
_LINK = re.compile(r"""<a [^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_EXACT = frozenset({"learn.microsoft.com", "go.microsoft.com", "download.microsoft.com"})
_SUFFIXES = (".azurefd.net", ".web.core.windows.net")

Transport = Callable[[str, int], bytes]


@dataclass(frozen=True, slots=True)
class ZipResult:
    set_id: str
    path: Path
    size: int
    skipped: bool


def _allowed(url: str) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    ok = host in _EXACT or any(host.endswith(suffix) for suffix in _SUFFIXES)
    if parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password or not ok:
        raise LibError(
            f"refusing to fetch {url}",
            "only the Open Specifications pages and Microsoft's own download hosts are allowed",
        )


def _text(html: str) -> str:
    return _SPACE.sub(" ", _TAG.sub("", html)).strip()


def zip_link(html: str, label: str, page: str) -> str:
    """The zip href whose anchor names `label`, resolved against `page`."""
    wanted = label.casefold()
    found: list[tuple[int, str]] = []
    for href, raw in _LINK.findall(html):
        text = _text(raw)
        if "zip" not in text.casefold() or wanted not in text.casefold():
            continue
        absolute = href if href.lower().startswith("https://") else ""
        if absolute:
            found.append((len(text), absolute))
    if not found:
        raise LibError(
            f"the page for {label} has no zip link",
            "the Open Specifications download table changed; the page is recorded in the catalogue",
            page,
        )
    found.sort()
    url = found[0][1]
    _allowed(url)
    return url


def resolve(url: str, *, opener: urllib.request.OpenerDirector | None = None) -> str:
    """Follow redirects and return the final URL. Each hop has to be an allowed host."""
    _allowed(url)

    class _Guard(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            _allowed(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    agent = opener or urllib.request.build_opener(_Guard)
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
    require_network(url, "msos")
    try:
        with agent.open(request, timeout=60) as response:
            final = str(response.geturl())
    except LibError:
        raise
    except Exception as exc:
        raise LibError(f"could not resolve {url}: {exc}", "retry; the fwlink should redirect to the zip") from exc
    _allowed(final)
    return final


def _length(url: str) -> int | None:
    _allowed(url)
    require_network(url, "msos")
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            value = response.headers.get("Content-Length")
    except Exception:
        return None
    return int(value) if value and value.isdigit() else None


def _stream(url: str, dest: Path) -> int:
    """Write `url` to `dest`. Returns the size. A body over the cap is discarded."""
    _allowed(url)
    require_network(url, "msos")
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    digest = hashlib.sha256()
    part = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:  # noqa: S310
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ZIP:
                    raise LibError(f"{url} is over the {MAX_ZIP} byte cap", "the zip was discarded")
                digest.update(chunk)
                out.write(chunk)
    except LibError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise LibError(f"download of {url} failed: {exc}", "retry the same sync") from exc
    part.replace(dest)
    return dest.stat().st_size


def _page(url: str, transport: Transport | None) -> str:
    _allowed(url)
    if transport is not None:
        data = transport(url, MAX_PAGE)
    else:
        require_network(url, "msos")
        request = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read(MAX_PAGE + 1)
        except Exception as exc:
            raise LibError(f"could not read {url}: {exc}", "retry") from exc
    if len(data) > MAX_PAGE:
        raise LibError(f"{url} is over the {MAX_PAGE} byte page cap", "")
    return data.decode("utf-8", "replace")


def choose(resolved: str, direct: str) -> str:
    """The zip URL: `resolved` when it is a zip, otherwise the catalogue's direct address."""
    if urlsplit(resolved).path.lower().endswith(".zip"):
        return resolved
    if direct:
        return direct
    raise LibError(
        f"{resolved} is not a zip",
        "the Open Specifications download link no longer points at a zip",
    )


def sync_sets(
    home: Path,
    only: Sequence[str] = (),
    *,
    transport: Transport | None = None,
    resolve_url: Callable[[str], str] | None = None,
) -> list[ZipResult]:
    """Download each catalogue zip that is missing or whose resolved URL now serves a different size."""
    wanted = set(only)
    unknown = wanted - {item.id for item in SETS} - {WIM_ID}
    if unknown:
        from primarysource.msos.catalogue import by_id

        by_id(sorted(unknown)[0])
    home.mkdir(parents=True, exist_ok=True)
    (home / ZIPS).mkdir(exist_ok=True)
    pages: dict[str, str] = {}
    results: list[ZipResult] = []
    failed: list[str] = []
    follow = resolve_url or resolve
    for item in SETS:
        if wanted and item.id not in wanted:
            continue
        try:
            _one(item, home, pages, results, transport, follow)
        except LibError as exc:
            failed.append(item.id)
            print(f"error: {item.id}: {exc.message}", file=sys.stderr, flush=True)
    if not wanted or WIM_ID in wanted:
        try:
            results.append(sync_wim(home, transport=transport))
        except LibError as exc:
            failed.append(WIM_ID)
            print(f"error: {WIM_ID}: {exc.message}", file=sys.stderr, flush=True)
    if failed:
        raise LibError(
            f"could not download {', '.join(failed)}",
            "the zips that succeeded are kept; retry sync for the rest",
        )
    return results


def _one(
    item: SpecSet,
    home: Path,
    pages: dict[str, str],
    results: list[ZipResult],
    transport: Transport | None,
    follow: Callable[[str], str],
) -> None:
    html = pages.get(item.page)
    if html is None:
        html = _page(item.page, transport)
        pages[item.page] = html
    linked = zip_link(html, item.label, item.page)
    if transport is not None:
        final = linked
    else:
        try:
            resolved = follow(linked)
        except LibError as exc:
            if not item.direct:
                raise
            print(f"note {item.id}: {exc.message}", file=sys.stderr, flush=True)
            resolved = item.direct
        final = choose(resolved, item.direct)
        _allowed(final)
    dest = home / ZIPS / f"{item.id}.zip"
    if transport is not None:
        body = transport(final, MAX_ZIP)
        if len(body) > MAX_ZIP:
            raise LibError(f"{final} is over the {MAX_ZIP} byte cap", "")
        if dest.is_file() and sha256_file(dest) == hashlib.sha256(body).hexdigest():
            results.append(ZipResult(item.id, dest, dest.stat().st_size, True))
            return
        atomic_write(dest, body)
        results.append(ZipResult(item.id, dest, len(body), False))
        return
    remote = _length(final)
    if dest.is_file() and remote is not None and dest.stat().st_size == remote:
        print(f"skip {item.id} {dest.stat().st_size}", file=sys.stderr, flush=True)
        results.append(ZipResult(item.id, dest, dest.stat().st_size, True))
        return
    print(f"get {item.id} {final}", file=sys.stderr, flush=True)
    size = _stream(final, dest)
    print(f"ok {item.id} {size}", file=sys.stderr, flush=True)
    results.append(ZipResult(item.id, dest, size, False))


def wim_path(home: Path) -> Path:
    """Where the Windows Imaging File Format paper is stored."""
    return home / WIM_ID / WIM_NAME


def sync_wim(home: Path, *, transport: Transport | None = None) -> ZipResult:
    """Download the Windows Imaging File Format paper. It is not in the Open Specifications zips.

    The stable page is `WIM_PAGE`. The file URL is the Download Center address for that page.
    """
    _allowed(WIM_URL)
    dest = wim_path(home)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if transport is not None:
        body = transport(WIM_URL, MAX_ZIP)
        if len(body) > MAX_ZIP:
            raise LibError(f"{WIM_URL} is over the {MAX_ZIP} byte cap", "")
        if dest.is_file() and sha256_file(dest) == hashlib.sha256(body).hexdigest():
            return ZipResult(WIM_ID, dest, dest.stat().st_size, True)
        atomic_write(dest, body)
        return ZipResult(WIM_ID, dest, len(body), False)
    remote = _length(WIM_URL)
    if dest.is_file() and remote is not None and dest.stat().st_size == remote:
        print(f"skip {WIM_ID} {dest.stat().st_size}", file=sys.stderr, flush=True)
        return ZipResult(WIM_ID, dest, dest.stat().st_size, True)
    print(f"get {WIM_ID} {WIM_URL}", file=sys.stderr, flush=True)
    size = _stream(WIM_URL, dest)
    print(f"ok {WIM_ID} {size}", file=sys.stderr, flush=True)
    return ZipResult(WIM_ID, dest, size, False)
