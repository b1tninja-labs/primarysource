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
HOSTS = (
    "www.bluetooth.com",
    "www.bluetooth.org",
    "files.bluetooth.com",
    "btprodspecificationrefs.blob.core.windows.net",
)
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
    """One document of the listing. `slug` (the last part of its page's address) is its `doc_id`.

    `pdf` is set only for a supplement whose PDF is not linked from a row of the listing (see `SUPPLEMENTS`): the
    fetch then takes the PDF from here, not from the page. `clauses`, when set, limits what is kept of the document
    to those clause numbers and their subsections; everything else in the PDF is read past and not written.
    `located` names (clause, heading) pairs the PDF's heading splitter misses in this edition, so each is found by its
    exact heading line instead.
    """

    slug: str
    title: str
    revision: str
    type: str
    status: str
    deprecation: str
    withdrawal: str
    page: str
    pdf: str = ""
    clauses: tuple[str, ...] = ()
    located: tuple[tuple[str, str], ...] = ()

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


GSS_PAGE = "https://www.bluetooth.com/specifications/gss/"
GSS_PDF = "https://btprodspecificationrefs.blob.core.windows.net/gatt-specification-supplement/GATT_Specification_Supplement.pdf"
AN_PAGE = "https://www.bluetooth.com/specifications/assigned-numbers/"
AN_PDF = "https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Assigned_Numbers/out/en/Assigned_Numbers.pdf"

# Clauses of the two supplements kept for the OBD bridge's serial/UART GATT, ATT and L2CAP basics. A listed clause
# keeps its own text and every subsection of it. Medical, health, bio and body-sensor clauses are not listed, so they
# are read past and never written to the corpus. Read 2026-11-21 against the PDFs' own contents pages.
#   GSS (GATT Specification Supplement, 2026-09-09): §3 is a catalogue of sensor and measurement characteristics, none
#   of them needed for the bridge, so none of §3 is kept. §4.1 Valid Range is the one descriptor the document defines.
GSS_CLAUSES: tuple[str, ...] = ("1", "2.1", "2.2", "2.3", "2.4", "4", "4.1")
#   Assigned Numbers (2026-11-16): the GATT service and characteristic identifiers (§3.4, §3.8), the attribute types
#   for declarations (§3.6) and the descriptor identifiers, CCCD among them (§3.7), the LE fixed channel identifiers
#   (§2.9), the PSM values (§2.5), the presentation format descriptor (§2.4), the common data types (§2.3), and the
#   GAP appearance definition (§2.6.1). The §3.4 and §3.8 tables list every SIG service and characteristic by
#   identifier in one clause each, so their health rows come with them as identifiers only; no profile clause is kept.
AN_CLAUSES: tuple[str, ...] = ("1", "2.3", "2.4", "2.5", "2.6.1", "2.9", "3.4", "3.6", "3.7", "3.8")
# The PDF has no heading for chapter 3, and the splitter accepts a numbered heading only under a parent it has seen,
# so it finds none of 3.4, 3.6, 3.7 or 3.8 (it finds some of their subsections). These four are located by their exact
# heading lines instead (`importer._cut`).
AN_LOCATED: tuple[tuple[str, str], ...] = (
    ("3.4", "GATT Services"),
    ("3.6", "Declarations"),
    ("3.7", "Descriptors"),
    ("3.8", "Characteristics"),
)

# The two supplements. Neither appears as a row of the listing, so the catalogue adds them by hand: the SIG's own
# page for each gives the PDF's address, and the PDF's front page gives the version. Their status is `published`
# (the pages carry no status word), so `fetch` with no slugs does not take them; name them to fetch them.
SUPPLEMENTS: tuple[Entry, ...] = (
    Entry(
        slug="gatt-specification-supplement",
        title="GATT Specification Supplement",
        revision="2026-09-09",
        type="Supplemental Document",
        status="published",
        deprecation="",
        withdrawal="",
        page=GSS_PAGE,
        pdf=GSS_PDF,
        clauses=GSS_CLAUSES,
    ),
    Entry(
        slug="assigned-numbers",
        title="Assigned Numbers",
        revision="2026-11-16",
        type="Supplemental Document",
        status="published",
        deprecation="",
        withdrawal="",
        page=AN_PAGE,
        pdf=AN_PDF,
        clauses=AN_CLAUSES,
        located=AN_LOCATED,
    ),
)


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


_FORCE_LINK = re.compile(r"href=\"(?P<href>https://files\.bluetooth\.com/[^\"]*dlm-dp-dl-force=1[^\"]*)\"", re.I)


def parse_download_page(page: str) -> str | None:
    """files.bluetooth.com answers a download address with a page that says the download starts by itself, and links
    the file with a one-time nonce. That link, or None when the page has none."""
    found = _FORCE_LINK.search(page)
    return html.unescape(found["href"]) if found else None


def write(path: Path, entries: list[Entry]) -> None:
    from primarysource.fsutil import atomic_write

    payload = {"schema": SCHEMA, "source": LISTING_URL, "entries": [asdict(e) for e in entries]}
    atomic_write(path, (json.dumps(payload, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def read(path: Path) -> list[Entry]:
    """The cached catalogue, or a `LibError` naming the command that makes it."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            Entry(
                **{
                    **e,
                    "clauses": tuple(e.get("clauses", ())),
                    "located": tuple((c, t) for c, t in e.get("located", ())),
                }
            )
            for e in raw["entries"]
        ]
    except (OSError, ValueError, KeyError, TypeError):
        raise LibError(f"no catalogue at {path}", "primarysource bluetooth catalogue") from None
