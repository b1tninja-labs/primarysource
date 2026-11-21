"""The Open Specifications table of contents on learn.microsoft.com.

The library is not one file. `https://learn.microsoft.com/en-us/openspecs/toc.json` lists the families, each
family directory has its own `toc.json`, and each specification directory has one more, whose entries are the
section pages. This module only parses those files and turns their hrefs into absolute page URLs. Nothing here
fetches.

One article is not in that tree. The on-disk registry hive is described by an archived Technet page, so
`SUPPLEMENTS` names it and the crawl records it beside the tables of contents.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Iterable
from dataclasses import dataclass

from primarysource.errors import LibError

HOST = "learn.microsoft.com"
ROOT_TOC = "https://learn.microsoft.com/en-us/openspecs/toc.json"
HOSTS = (HOST,)
MAX_TOC_BYTES = 4 * 1024 * 1024
"""A family table of contents is tens of kilobytes. Anything larger is not the file this parser expects."""

_TAG = re.compile(r"\[((?:MS|MC)-[A-Z0-9]+)\]")
_SLUG = re.compile(r"(?i)^(?:ms|mc)-[a-z0-9]+$")
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-")
_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)(?![0-9A-Za-z])")
DOC_ID = re.compile(r"(?:MS|MC|TN)-[A-Z0-9]+")
SECTION_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z.\-]*")


@dataclass(frozen=True, slots=True)
class Supplement:
    """A Learn page the Open Specifications tables do not list. `doc` is the catalog id, not a Microsoft tag."""

    doc: str
    title: str
    url: str


# Archived Technet article that describes the on-disk hive: the base block and the bins. The protocol
# specifications name hive files and do not contain this page, so the table-of-contents walk never reaches it.
SUPPLEMENTS = (
    Supplement(
        "TN-CC750583",
        "Inside the Registry",
        "https://learn.microsoft.com/en-us/previous-versions/cc750583(v=technet.10)",
    ),
)


def resolve(toc_url: str, href: str) -> str | None:
    """An absolute `https://learn.microsoft.com/en-us/openspecs/...` page, or None when `href` is not one.

    Learn's tables of contents mix `/openspecs/...` (no locale) with paths relative to the `toc.json`. Both
    become the `/en-us/openspecs/` page this fetcher is allowed to request. A `toc.json` link is not a page.
    """
    text = href.strip()
    if not text or text.startswith(("#", "mailto:", "javascript:")):
        return None
    joined = urllib.parse.urljoin(toc_url, text)
    parts = urllib.parse.urlsplit(joined)
    if parts.hostname not in (None, HOST) or parts.scheme not in ("https", ""):
        return None
    path = parts.path
    if not path.startswith("/en-us/"):
        path = "/en-us" + (path if path.startswith("/") else "/" + path)
    if not path.startswith("/en-us/openspecs/") or path.endswith("/toc.json"):
        return None
    return urllib.parse.urlunsplit(("https", HOST, path, "", ""))


def toc_of(page_url: str) -> str:
    """The `toc.json` beside `page_url`: the directory that holds that page."""
    path = urllib.parse.urlsplit(page_url).path.rsplit("/", 1)[0]
    return urllib.parse.urlunsplit(("https", HOST, path + "/toc.json", "", ""))


def doc_id(url: str, title: str) -> str | None:
    """`MS-SMB2` from a `[MS-SMB2]` title, else from the `ms-smb2` directory. None for a page that is neither."""
    tag = _TAG.search(title)
    if tag:
        return tag.group(1)
    parts = [part for part in urllib.parse.urlsplit(url).path.split("/") if part]
    if len(parts) < 4 or parts[0] != "en-us" or parts[1] != "openspecs":
        return None
    slug = parts[-2] if _GUID.match(parts[-1]) else parts[-1]
    if _SLUG.fullmatch(slug):
        return slug.upper()
    return None


def section_id(title: str, used: Iterable[str]) -> str:
    """The section number the title starts with, or a slug of the title, unique within `used`."""
    taken = set(used)
    match = _NUMBER.match(title.strip())
    base = match.group(1) if match else _slug(title)
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def pages_from_toc(body: bytes, toc_url: str) -> list[tuple[str, str, int]]:
    """`(page url, title, depth)` in the order the table lists them. A file that is not a table is an error."""
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise LibError(f"{toc_url} is not JSON", "retry; the table of contents should be a JSON object") from exc
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LibError(
            f"{toc_url} is not an Open Specifications table of contents",
            "retry; the file should contain an items array",
        )
    found: list[tuple[str, str, int]] = []
    for item in items:
        _walk(item, 1, toc_url, found)
    return found


def _walk(node: object, depth: int, toc_url: str, found: list[tuple[str, str, int]]) -> None:
    if not isinstance(node, dict):
        return
    href = node.get("href")
    title = node.get("toc_title") if isinstance(node.get("toc_title"), str) else node.get("title")
    if isinstance(href, str) and isinstance(title, str) and title.strip():
        url = resolve(toc_url, href)
        if url is not None:
            found.append((url, title.strip(), depth))
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            _walk(child, depth + 1, toc_url, found)


def _slug(title: str) -> str:
    chars: list[str] = []
    for char in title.casefold():
        if char.isascii() and char.isalnum():
            chars.append(char)
        elif chars and chars[-1] != "-":
            chars.append("-")
    return "".join(chars).strip("-")[:80] or "page"
