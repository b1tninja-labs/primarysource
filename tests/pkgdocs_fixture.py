"""Synthesised archives and a one-tree collection for the pkgdocs tests. No real text anywhere."""

from __future__ import annotations

import gzip
import io
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import IO

from primarysource.pkgdocs import fetch
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.readers.markdown import read_markdown
from primarysource.pkgdocs.runtime import Build, Library, Licence, Pin, Spec, TreeSpec, matching

COMMIT = "a" * 40
OTHER = "b" * 40
URL = "https://forge.invalid/repo/archive.tar.gz"
MIRROR = "https://mirror.invalid/repo/archive.tar.gz"

ALPHA = """# Alpha

Intro words about widgets.

## First part

Text about gaskets and sprockets.

Another paragraph on gaskets.

## Second part

Nothing about the first.

### Notes

Some notes on sprockets.

## First part

A repeated heading.
"""

BETA = """# Beta

Beta intro.

## C# notes

Hash in a title.
"""

FILES = {"docs/alpha.md": ALPHA.encode(), "docs/beta.md": BETA.encode(), "docs/skip.bin": b"\x00\x01"}


def make_tar(
    members: Mapping[str, bytes],
    *,
    prefix: str = "repo-aaaa/",
    gz: bool = True,
    links: Mapping[str, tuple[bytes, str]] | None = None,
) -> bytes:
    """A tar of `members` (name -> data) under `prefix`; `links` maps a name to (type, target) for symlinks
    (`b"s"`) and hard links (`b"h"`)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        top = tarfile.TarInfo(prefix.rstrip("/"))
        top.type = tarfile.DIRTYPE
        tar.addfile(top)
        for name, data in members.items():
            info = tarfile.TarInfo(name if name.startswith("/") or ".." in name else prefix + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, (kind, target) in (links or {}).items():
            link = tarfile.TarInfo(prefix + name)
            link.type = tarfile.SYMTYPE if kind == b"s" else tarfile.LNKTYPE
            link.linkname = target
            tar.addfile(link)
    raw = buffer.getvalue()
    return gzip.compress(raw, mtime=0) if gz else raw


def opener_for(archives: Mapping[str, bytes], seen: list[str] | None = None) -> fetch.Opener:
    """A transport that serves `archives` by URL and fails like a network for anything else."""

    def open_url(request: urllib.request.Request) -> IO[bytes]:
        url = request.full_url
        if seen is not None:
            seen.append(url)
        if url not in archives:
            raise urllib.error.URLError(f"no route to {url}")
        return io.BytesIO(archives[url])

    return open_url


def no_wait() -> fetch.Throttle:
    return fetch.Throttle(interval=0, sleep=lambda _: None)


def _build(files: Mapping[str, bytes], pin: Pin) -> Build:
    docs = [read_markdown(files[p], p[len("docs/") : -3]).with_meta(path=p) for p in sorted(files)]
    return Build(tuple(docs), {"a": "alpha", "1": "alpha"}, {})


def manifest_for(members: Mapping[str, bytes], include: Callable[[str], bool]) -> str:
    return fetch.manifest_digest({k: v for k, v in members.items() if include(k)})


INCLUDE = matching(r"docs/[a-z]+\.md")


def make_spec(digest: str | None, *, commit: str = COMMIT, sources: tuple[Source, ...] | None = None) -> Spec:
    pin = Pin(commit, "v1", "2026-01-01", digest, sources or (Source(URL, strip=1),))
    return Spec(
        name="demo",
        title="Demo documents",
        licence=Licence("CC0-1.0", "layer", "nobody", "LICENSE", credit="CC0"),
        trees=(TreeSpec("main", "docs/ of a repository", (pin,), INCLUDE, _build),),
        instructions="demo",
        example_refs=("demo:alpha§First part",),
    )


def installed_library(tmp_path: Path) -> Library:
    digest = manifest_for(FILES, INCLUDE)
    library = Library(make_spec(digest), tmp_path / "home")
    library.import_edition(opener=opener_for({URL: make_tar(FILES)}), throttle=no_wait())
    return library
