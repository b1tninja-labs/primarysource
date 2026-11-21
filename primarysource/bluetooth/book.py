"""Turn a downloaded HTML book into sections.

The catalog page links `index-en.html`. A short specification is that one file. The Core Specification's index
is a table of contents whose links are the volume and part files. A link that leaves the book's directory is
not part of the book.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from primarysource.readers.html import Profile, convert

HOST = "www.bluetooth.com"
_PROFILE = Profile(chrome_classes=frozenset({"toc-wrapper", "toc-placeholder", "page-tools", "logotype-container"}))
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
_VOLUME = re.compile(r"^Volume\s+(\d+)\b")
_PART = re.compile(r"^Part\s+([A-Z])\b")
_HEADING = re.compile(r"^#{1,6}\s")
_SKIP = frozenset(
    {
        "note",
        "search results",
        "web site",
        "bluetooth core specification",
        "bluetooth® specification",
        "bluetooth® service specification",
    }
)


@dataclass(frozen=True, slots=True)
class Part:
    """One HTML file of a book and where it sits in the specification."""

    path: str
    url: str
    volume: str
    part: str


def parts(index_html: str, index_url: str) -> list[Part]:
    """The index file, then each other HTML file the index links, in order. A path that escapes is omitted."""
    found: list[Part] = []
    seen: set[str] = set()
    ancestors: list[tuple[int, str, str]] = []
    for href, level, text in _Topics().parse(index_html):
        while ancestors and ancestors[-1][0] >= level:
            ancestors.pop()
        parent_volume, parent_part = ancestors[-1][1:] if ancestors else ("", "")
        volume_match = _VOLUME.match(text)
        part_match = _PART.match(text)
        if volume_match:
            volume, part = volume_match.group(1), ""
        elif part_match:
            volume, part = parent_volume, part_match.group(1)
        else:
            volume, part = parent_volume, parent_part
        ancestors.append((level, volume, part))
        relative = _relative(index_url, href)
        if relative is None or relative in seen:
            continue
        seen.add(relative)
        found.append(Part(relative, urljoin(index_url, relative), volume, part))
    index = _relative(index_url, index_url)
    if index and index not in seen:
        found.insert(0, Part(index, index_url, "", ""))
    return found


def _relative(index_url: str, href: str) -> str | None:
    """A path relative to the index file's directory, or None when `href` is not a file of this book."""
    target = urljoin(index_url, unquote(href.split("#", 1)[0]))
    book = urlsplit(index_url)
    got = urlsplit(target)
    if got.scheme != "https" or got.hostname != HOST:
        return None
    directory = book.path.rsplit("/", 1)[0] + "/"
    if not got.path.startswith(directory) or not got.path.lower().endswith(".html"):
        return None
    relative = got.path[len(directory) :]
    if not relative or any(piece in ("", ".", "..") for piece in relative.split("/")):
        return None
    return relative


def sections(files: list[tuple[Part, str]]) -> list[dict[str, object]]:
    """Sections of the book in reading order. `files` is `(part, html)`."""
    built: list[dict[str, object]] = []
    used: set[str] = set()
    for part, html in files:
        document = convert(_content(html), part.path, _PROFILE)
        kept = [item for item in document.headings if item.text.strip().casefold() not in _SKIP]
        for index, heading in enumerate(kept):
            ident, title = _identity(heading.text, part.volume, part.part)
            ident = _unique(ident, used)
            end = kept[index + 1].block if index + 1 < len(kept) else len(document.blocks)
            units = [
                block.strip()
                for block in document.blocks[heading.block : end]
                if block.strip() and _HEADING.match(block) is None
            ]
            built.append({"id": ident, "title": title, "depth": heading.level, "units": units})
    return built


def _content(html: str) -> str:
    """The page from its content region on. The table of contents sits before that region."""
    for marker in ('id="content-wrapper"', "id='content-wrapper'", 'id="topic-content"'):
        at = html.find(marker)
        if at >= 0:
            return html[html.rfind("<", 0, at) :]
    return html


def _identity(text: str, volume: str, part: str) -> tuple[str, str]:
    numbered = _NUMBERED.match(text)
    if numbered:
        prefix = ".".join(piece for piece in (volume, part) if piece)
        ident = f"{prefix}.{numbered.group(1)}" if prefix else numbered.group(1)
        return ident, numbered.group(2).strip()
    volume_match = _VOLUME.match(text)
    if volume_match:
        rest = text.split(".", 1)[1].strip() if "." in text else text
        return f"vol-{volume_match.group(1)}", rest
    part_match = _PART.match(text)
    if part_match:
        prefix = f"{volume}.{part_match.group(1)}" if volume else part_match.group(1)
        rest = text.split(".", 1)[1].strip() if "." in text else text
        return prefix, rest
    return _slug(text), text


def _unique(ident: str, used: set[str]) -> str:
    candidate = ident
    suffix = 2
    while candidate in used:
        candidate = f"{ident}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _slug(text: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in text]
    slug = re.sub(r"-{2,}", "-", "".join(chars)).strip("-")
    return slug[:80] or "section"


class _Topics(HTMLParser):
    """`(href, level, text)` for the book's topic links, in order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._found: list[tuple[str, int, str]] = []
        self._href = ""
        self._level = 0
        self._text: list[str] = []

    def parse(self, html: str) -> list[tuple[str, int, str]]:
        self.feed(html)
        self.close()
        return self._found

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href:
            return
        attr = {key: value or "" for key, value in attrs}
        level = attr.get("data-topic-level")
        href = attr.get("href", "")
        if not level or not level.isdigit() or not href:
            return
        self._href = href
        self._level = int(level)
        self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self._found.append((self._href, self._level, " ".join("".join(self._text).split())))
            self._href = ""

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)
