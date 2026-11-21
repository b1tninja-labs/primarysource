"""Parse the Ecma standards index and one standard's page.

The index captured on 2026-11-17 (`/publications-and-standards/standards/`) is one
`ul.items-list-wrapper`: a header row, then one `li` per standard with the number, the title
and the last-change date. That page links to `/publications-and-standards/withdrawn-standards/`,
which uses the same list. A standard's own page names the current edition (`p.ecma-item-edition`
and the `a.download` that is not in the archive) and older editions (`ul.ecma-item-archives`).
No PDF is linked from the index. Nothing here fetches.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from primarysource.ecma.catalogue import HOSTS, NUMBER
from primarysource.errors import LibError
from primarysource.fetch import check_url

INDEX_URL = "https://ecma-international.org/publications-and-standards/standards/"
_ORIGIN = "https://ecma-international.org/"
_EDITION = re.compile(r"^([0-9]{1,2})(?:st|nd|rd|th) edition, .+$")
_ARCHIVE = re.compile(r"^ECMA-([0-9]{1,4}), ([0-9]{1,2}(?:st|nd|rd|th) edition, .+)$")
_NUMBER = re.compile(r"^ECMA-([0-9]{1,4})$")


@dataclass(frozen=True, slots=True)
class Listing:
    """One row of the standards index or the withdrawn list."""

    number: str
    title: str
    changed: str
    page_url: str
    list_name: str


@dataclass(frozen=True, slots=True)
class PageEdition:
    """One edition named on a standard's page, current or archived."""

    number: str
    edition: int
    edition_name: str
    title: str
    source_url: str
    current: bool


def _absolute(href: str) -> str:
    url = urllib.parse.urljoin(_ORIGIN, href.strip())
    check_url(url, HOSTS)
    return url


def _flat(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


class _IndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.listings: list[Listing] = []
        self.withdrawn: str | None = None
        self._ul = 0
        self._li = False
        self._header = False
        self._span: dict[str, Any] | None = None
        self._spans: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = attr.get("class", "").split()
        if tag == "a" and "/publications-and-standards/withdrawn-standards" in attr.get("href", ""):
            self.withdrawn = self.withdrawn or attr["href"]
        if tag == "ul" and "items-list-wrapper" in classes:
            self._ul += 1
            return
        if self._ul and tag == "li":
            self._li = True
            self._header = "list-header" in classes
            self._spans = []
            self._span = None
            return
        if self._li and tag == "span" and self._span is None:
            self._span = {"href": None, "parts": []}
            return
        if self._span is not None and tag == "a" and not self._span["href"]:
            self._span["href"] = attr.get("href") or None

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._span is not None:
            self._spans.append(self._span)
            self._span = None
            return
        if tag == "li" and self._li:
            self._li = False
            if not self._header:
                self._close_item()
            return
        if tag == "ul" and self._ul:
            self._ul -= 1

    def handle_data(self, data: str) -> None:
        if self._span is not None:
            self._span["parts"].append(data)

    def _close_item(self) -> None:
        if len(self._spans) < 3:
            return
        number_text = _flat(self._spans[0]["parts"])
        title = _flat(self._spans[1]["parts"])
        changed = _flat(self._spans[2]["parts"])
        href = self._spans[0]["href"] or self._spans[1]["href"]
        match = _NUMBER.fullmatch(number_text)
        if match is None or not title or not changed or not href:
            raise LibError(
                f"a standards-index row could not be read ({number_text!r})",
                "the index row is a number, a title and a last-change date",
            )
        self.listings.append(Listing(match.group(1), title, changed, _absolute(href), ""))


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.h1: list[str] = []
        self.title: list[str] = []
        self.edition: list[str] = []
        self.current_pdf: str | None = None
        self.archives: list[tuple[str, str]] = []
        self._in_h1 = False
        self._capture: list[str] | None = None
        self._archives = 0
        self._label: list[str] | None = None
        self._href: str | None = None
        self._in_archive_li = False
        self._in_archive_a = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())
        if tag == "h1":
            self._in_h1 = True
            self.h1 = []
        elif tag == "p" and "ecma-item-short-description" in classes:
            self._capture = self.title = []
        elif tag == "p" and "ecma-item-edition" in classes:
            self._capture = self.edition = []
        elif tag == "ul" and "ecma-item-archives" in classes:
            self._archives += 1
        elif tag == "li" and self._archives:
            self._in_archive_li = True
            self._label = []
            self._href = None
        elif tag == "a" and self._in_archive_li and attr.get("href"):
            self._href = attr["href"]
            self._in_archive_a = True
        elif tag == "a" and "download" in classes and not self._archives and attr.get("href"):
            if self.current_pdf is not None:
                raise LibError("the standard page has two current downloads", "one current edition is expected")
            self.current_pdf = attr["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_archive_a:
            self._in_archive_a = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "p" and self._capture is not None and not self._in_archive_li:
            self._capture = None
        elif tag == "li" and self._in_archive_li:
            self._in_archive_li = False
            label = _flat(self._label or [])
            if label and self._href:
                self.archives.append((label, self._href))
            self._label = None
        elif tag == "ul" and self._archives:
            self._archives -= 1

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.h1.append(data)
        elif self._capture is not None:
            self._capture.append(data)
        elif self._label is not None and not self._in_archive_a:
            self._label.append(data)


def parse_index(html: str, list_name: str) -> tuple[tuple[Listing, ...], str | None]:
    """The index rows, and the withdrawn-list URL when this page links to one."""
    parser = _IndexParser()
    parser.feed(html)
    parser.close()
    if not parser.listings:
        raise LibError(
            "the standards index had no rows",
            "expected ul.items-list-wrapper with a number, a title and a last-change date",
        )
    numbers = [row.number for row in parser.listings]
    if len(numbers) != len(set(numbers)):
        raise LibError("the standards index lists a number twice", "one row per standard")
    if list_name not in ("standards", "withdrawn"):
        raise LibError(f"unknown list {list_name!r}", "standards or withdrawn")
    rows = tuple(Listing(row.number, row.title, row.changed, row.page_url, list_name) for row in parser.listings)
    withdrawn = _absolute(parser.withdrawn) if parser.withdrawn else None
    return rows, withdrawn


def _edition_number(name: str) -> int:
    match = _EDITION.fullmatch(name.strip())
    if match is None:
        raise LibError(f"not an edition label: {name!r}", "expected '1st edition, January 2026'")
    return int(match.group(1))


def parse_standard(html: str, number: str) -> tuple[PageEdition, ...]:
    """The current edition and every archived edition on one standard's page."""
    if not NUMBER.fullmatch(number):
        raise LibError(f"not an Ecma standard number: {number!r}", "use the number, e.g. 427")
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    heading = _flat(parser.h1)
    if heading != f"ECMA-{number}":
        raise LibError(
            f"this page is {heading or 'untitled'}, not ECMA-{number}",
            "fetch the standard's own page",
        )
    title = _flat(parser.title)
    current_name = _flat(parser.edition)
    if not title or not current_name or not parser.current_pdf:
        raise LibError(
            f"ECMA-{number}: the page has no current edition",
            "expected the edition line and one download link outside the archive",
        )
    found: list[PageEdition] = [
        PageEdition(
            number,
            _edition_number(current_name),
            current_name,
            title,
            _absolute(parser.current_pdf),
            True,
        )
    ]
    for label, href in parser.archives:
        match = _ARCHIVE.fullmatch(label.strip())
        if match is None or match.group(1) != number:
            raise LibError(f"ECMA-{number}: an archive row could not be read ({label!r})", "")
        found.append(
            PageEdition(number, _edition_number(match.group(2)), match.group(2), title, _absolute(href), False)
        )
    editions = [row.edition for row in found]
    if len(editions) != len(set(editions)):
        raise LibError(f"ECMA-{number}: the page names an edition twice", "")
    return tuple(found)
