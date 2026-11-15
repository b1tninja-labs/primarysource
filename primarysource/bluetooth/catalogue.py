"""The Bluetooth SIG's list of specifications, read from bluetooth.com/specifications/specs/.

The listing is server-rendered HTML, one table row per document: name, revision, type, status, deprecation and
withdrawal dates, and a link to the document's own page. That page lists the files; the specification's PDF is the
first row whose label is not a test document (a test suite, an ICS, an IXIT, a test case reference list, a list of
changes or an erratum). A document with no such row (HTML only) has no PDF to fetch.

`parse_listing` and `parse_spec_page` read text they are given and make no request, so they are tested over invented
pages. The catalogue is cached as `catalogue.json` in the collection's home by `primarysource bluetooth catalogue`.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from primarysource.errors import LibError

LISTING_URL = "https://www.bluetooth.com/specifications/specs/"
HOSTS = ("www.bluetooth.com", "www.bluetooth.org", "files.bluetooth.com")
SPEC_PREFIX = "https://www.bluetooth.com/specifications/specs/"
SCHEMA = 1

_ROW = re.compile(r"<tr\b[^>]*\bclass=\"[^\"]*\bindex-item\b[^\"]*\"[^>]*>(?P<body>.*?)</tr>", re.S | re.I)
_TITLE = re.compile(r"<td class=\"title\">\s*<a href=\"(?P<url>[^\"]+)\"[^>]*>(?P<name>.*?)</a>", re.S | re.I)
_CELL = re.compile(
    r"<td class=\"(?P<name>revision|type|status|deprecation|withdrawal)\"[^>]*>(?P<text>.*?)</td>", re.S | re.I
)
_TABLE_ROW = re.compile(r"<tr\b[^>]*>(?P<body>.*?)</tr>", re.S | re.I)
_ANCHOR = re.compile(r"<a\b[^>]*\bhref=\"(?P<href>[^\"]+)\"[^>]*>(?P<text>.*?)</a>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_DOWNLOAD = re.compile(r"DownloadDoc\.ashx\?doc_id=\d+|files\.bluetooth\.com/download/", re.I)
_NOT_THE_SPEC = re.compile(
    r"test suite|conformance|ixit|test case|changes since|errata|erratum|\(ts\)|\(ics\)|test specification|test plan",
    re.I,
)


@dataclass(frozen=True, slots=True)
class Entry:
    """One document of the listing. `slug` (the last part of its page's address) is its `doc_id`."""

    slug: str
    title: str
    revision: str
    type: str
    status: str
    deprecation: str
    withdrawal: str
    page: str

    @property
    def number(self) -> str:
        """The citation name: `Bluetooth <title> <revision>`."""
        return " ".join(part for part in ("Bluetooth", self.title, self.revision) if part)

    @property
    def corpus_status(self) -> str:
        """`final` for an adopted document in force, else what the listing says (the tools warn if not final)."""
        if self.withdrawal:
            return "withdrawn"
        if self.deprecation:
            return "deprecated"
        return "final" if self.status.lower() == "adopted" else (self.status.lower() or "unknown")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


def parse_listing(page: str) -> list[Entry]:
    """Every document of the listing page, in page order. A row that does not parse is skipped."""
    found: list[Entry] = []
    seen: set[str] = set()
    for row in _ROW.finditer(page):
        body = row["body"]
        title = _TITLE.search(body)
        if title is None or not title["url"].startswith(SPEC_PREFIX):
            continue
        slug = title["url"].removeprefix(SPEC_PREFIX).strip("/")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug) or slug in seen:
            continue
        cells = {m["name"].lower(): _text(m["text"]) for m in _CELL.finditer(body)}
        seen.add(slug)
        found.append(
            Entry(
                slug=slug,
                title=_text(title["name"]),
                revision=cells.get("revision", ""),
                type=cells.get("type", ""),
                status=cells.get("status", ""),
                deprecation=cells.get("deprecation", ""),
                withdrawal=cells.get("withdrawal", ""),
                page=title["url"],
            )
        )
    return found


def parse_spec_page(page: str) -> str | None:
    """The address of the specification's own PDF on its page, or None when the page offers none."""
    for row in _TABLE_ROW.finditer(page):
        cells = re.split(r"</td>", row["body"], flags=re.I)
        if len(cells) < 2:
            continue
        label = _text(cells[0])
        if _NOT_THE_SPEC.search(label):
            continue
        for anchor in _ANCHOR.finditer(row["body"]):
            href = html.unescape(anchor["href"]).strip()
            if _DOWNLOAD.search(href) and _text(anchor["text"]).lower() == "pdf":
                return href
    return None


def write(path: Path, entries: list[Entry]) -> None:
    from primarysource.fsutil import atomic_write

    payload = {"schema": SCHEMA, "source": LISTING_URL, "entries": [asdict(e) for e in entries]}
    atomic_write(path, (json.dumps(payload, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def read(path: Path) -> list[Entry]:
    """The cached catalogue, or a `LibError` naming the command that makes it."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Entry(**e) for e in raw["entries"]]
    except (OSError, ValueError, KeyError, TypeError):
        raise LibError(f"no catalogue at {path}", "primarysource bluetooth catalogue") from None
