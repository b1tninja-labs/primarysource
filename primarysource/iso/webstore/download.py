"""Downloading a PDF the owner holds: stream to a `.part`, verify, then `os.replace`.

The URL is the one `obp.parse_products` found (`/obp/ui/APP/connector/<ui>/<id>/dl`), valid for one UI session and
for a product whose licence is assigned. The file goes to the collection's home (`docs/iso.md` section 1) by
default, never into a repository, under the name the server gives it (`ISO_IEC_26136_2024(en).pdf`), cleaned to a
plain file name. Nothing is extracted or indexed here: `primarysource iso import` does that.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError
from primarysource.fsutil import CHUNK, replace, sha256_file, write_lock
from primarysource.home import collection_home
from primarysource.iso.webstore.auth import ensure_outside_repo
from primarysource.iso.webstore.obp import DL_PATH
from primarysource.iso.webstore.session import BASE, WebstoreSession

MAX_BYTES = 512 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._()\- ]{0,120}\.pdf", re.IGNORECASE)
_DISPOSITION = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Downloaded:
    path: Path
    size: int
    sha256: str
    reused: bool
    """True when a file of the same digest was already there and was left alone."""


def server_filename(disposition: str | None) -> str:
    """The file name a `Content-Disposition` offers, reduced to a safe plain name, or a `LibError`."""
    match = _DISPOSITION.search(disposition or "")
    name = match[1].strip() if match else ""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if not _NAME.fullmatch(name):
        raise LibError("the server offered no usable PDF file name", "download it in a browser and name it by hand")
    return name


def download_owned(session: WebstoreSession, path: str, dest_dir: Path | None = None) -> Downloaded:
    """Stream one owned PDF into `dest_dir` (default: the iso collection home)."""
    if not DL_PATH.fullmatch(path):
        raise LibError("not a browsing-platform download path", "take it from obp.OwnedProduct.download_paths")
    target_dir = dest_dir or collection_home("iso")
    ensure_outside_repo(target_dir, "the download")
    target_dir.mkdir(parents=True, exist_ok=True)
    with session.stream(f"{BASE}{path}") as response:
        if response.status != 200:
            raise LibError(f"download: HTTP {response.status}", "the link is per UI session: open() a new one")
        dest = target_dir / server_filename(response.header("content-disposition"))
        part = dest.with_name(dest.name + ".part")
        digest = hashlib.sha256()
        size = 0
        with write_lock(part.with_name(part.name + ".lock"), what=str(part)) as lock:
            try:
                with part.open("wb") as out:
                    while chunk := response.read(CHUNK):
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise LibError(
                                "the download is larger than 512 MiB",
                                "this is not a standard's PDF; nothing was kept",
                            )
                        if size == len(chunk) and not chunk.startswith(b"%PDF-"):
                            raise LibError(
                                "the download is not a PDF", "the session may have expired; nothing was kept"
                            )
                        out.write(chunk)
                        digest.update(chunk)
                        lock.touch()
                if size == 0:
                    raise LibError("the download is empty", "nothing was kept")
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            hexdigest = digest.hexdigest()
            if dest.is_file() and sha256_file(dest) == hexdigest:
                part.unlink(missing_ok=True)
                return Downloaded(dest, size, hexdigest, True)
            replace(part, dest)
    return Downloaded(dest, size, hexdigest, False)
