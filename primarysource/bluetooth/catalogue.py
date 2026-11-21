"""The specification catalog published at bluetooth.com/specifications/specs/.

The page is one HTML table: document name, version, type and status, each name linked to its specification
page. That page links the HTML book. Nothing here fetches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from primarysource.errors import LibError

HOST = "www.bluetooth.com"
LISTING = "https://www.bluetooth.com/specifications/specs/"
HTML_ROOT = "https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/"
DOC = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SECTION = r"[0-9A-Za-z][0-9A-Za-z.\-]*"
_DOC = re.compile(DOC)
_SRC = re.compile(r"""[?&]src=([^&"'#]+)""", re.I)
_BOOK = re.compile(r"/index-en\.html?$", re.I)


@dataclass(frozen=True, slots=True)
class Spec:
    """One row of the public catalog."""

    doc: str
    title: str
    version: str
    kind: str
    status: str
    page: str


def doc_id(url: str) -> str | None:
    """The specification slug, the last path segment of its catalog page."""
    segment = urlsplit(url).path.strip("/").rsplit("/", 1)[-1].lower()
    return segment if _DOC.fullmatch(segment) else None


def parse_listing(html: str) -> list[Spec]:
    """The catalog rows. A page with none is an error: the table is the catalog."""
    rows = _Listing().parse(html)
    if not rows:
        raise LibError(
            "the Bluetooth specifications page has no catalog rows",
            "the table at bluetooth.com/specifications/specs/ should list each document",
            LISTING,
        )
    return rows


def book_url(html: str, page: str) -> str | None:
    """The HTML book's `index-en.html` linked from a specification page, or None when the page has none.

    A `src=` path is the book under the specification HTML root. Any other link is kept only when it is
    already an `index-en.html` on www.bluetooth.com.
    """
    for href in _Hrefs().parse(html):
        target = urljoin(page, unquote(href.strip()))
        src = _SRC.search(target)
        if src:
            tail = unquote(src.group(1)).lstrip("/")
            if _BOOK.search(tail):
                return HTML_ROOT + tail
        parts = urlsplit(target)
        if parts.hostname == HOST and parts.scheme == "https" and _BOOK.search(parts.path):
            return urljoin(target, parts.path)
    return None


class _Listing(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._rows: list[Spec] = []
        self._row = False
        self._cell = ""
        self._text: list[str] = []
        self._href: str | None = None
        self._cells: dict[str, str] = {}

    def parse(self, html: str) -> list[Spec]:
        self.feed(html)
        self.close()
        return self._rows

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "tr" and "index-item" in attr.get("class", "").split():
            self._row = True
            self._href = None
            self._cells = {}
            return
        if not self._row:
            return
        if tag == "td":
            self._cell = attr.get("class", "").split()[0] if attr.get("class") else ""
            self._text = []
        elif tag == "a" and self._cell == "title" and self._href is None:
            href = attr.get("href", "")
            if href:
                self._href = urljoin(LISTING, href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._row and self._cell:
            self._cells[self._cell] = " ".join("".join(self._text).split())
            self._cell = ""
        elif tag == "tr" and self._row:
            self._row = False
            self._finish()

    def handle_data(self, data: str) -> None:
        if self._cell:
            self._text.append(data)

    def _finish(self) -> None:
        href = self._href or ""
        doc = doc_id(href)
        title = self._cells.get("title", "")
        if doc is None or not title:
            return
        self._rows.append(
            Spec(
                doc,
                title,
                self._cells.get("revision", ""),
                self._cells.get("type", ""),
                self._cells.get("status", ""),
                href,
            )
        )


class _Hrefs(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hrefs: list[str] = []

    def parse(self, html: str) -> list[str]:
        self.feed(html)
        self.close()
        return self._hrefs

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._hrefs.append(href)
