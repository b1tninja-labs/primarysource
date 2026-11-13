"""Read the imported POSIX HTML edition: page outlines, budgeted reads by ref, and a bounded grep.

A page (`functions/open`) is converted with the collection's private HTML reader (`_html`, profile `POSIX`) into a
`primarysource.model.Document` whose sections are the page's headings, keyed by their HTML anchors
(`tag_17_372_03`). Each section's units are the blocks under its heading, the heading excluded and subsections
included. The core has no index yet, so there is no search here: `grep` scans pages, under a time and hit budget.
"""

from __future__ import annotations

import difflib
import html
import re
import time
from dataclasses import dataclass
from pathlib import Path

from primarysource import cursor
from primarysource.budget import page as budget_page
from primarysource.errors import LibError
from primarysource.ieee import POSIX, POSIX_PAGE, _html
from primarysource.ieee.catalogue import POSIX_2024, Edition
from primarysource.ieee.importer import INSTALL_RECORD, collection_home
from primarysource.model import Document, Section, span_hash
from primarysource.refs import Ref
from primarysource.render import next_start, render

VOLUMES = {"basedefs": "XBD", "functions": "XSH", "utilities": "XCU", "xrat": "XRAT"}
"""The four volumes' directories and their usual short names."""

MAX_NEEDLE = 200
MAX_HITS = 200
_PAGE = re.compile(POSIX_PAGE)
_TAGS = re.compile(r"<[^>]*>")


@dataclass(frozen=True, slots=True)
class Page:
    """One converted page: the model document plus the converter's output it was built from."""

    page: str
    document: Document
    converted: _html.Document

    def section_for(self, anchor: str) -> Section | None:
        """The section an anchor names: a heading's own anchor, or an id that sits just before a heading."""
        found = self.document.section(anchor)
        if found is None and anchor in self.converted.aliases:
            head = self.converted.headings[self.converted.aliases[anchor]]
            found = self.document.section(head.anchor)
        return found


def parse_page(data: bytes, page: str, edition: Edition = POSIX_2024) -> Page:
    """Convert one page's bytes. All 1,616 pages of the 2024 archive are UTF-8 (measured); a stray byte is
    replaced rather than refused, so one bad character cannot hide a page."""
    converted = _html.convert(data.decode("utf-8", errors="replace"), page, _html.POSIX)
    sections: list[Section] = []
    first = converted.headings[0].block if converted.headings else len(converted.blocks)
    if first:
        sections.append(Section("", converted.title or page, tuple(converted.blocks[:first]), 0))
    for position, head in enumerate(converted.headings):
        start, end = converted.span(position)
        anchor = head.anchor or f"_{position + 1}"
        sections.append(Section(anchor, head.text, tuple(converted.blocks[start + 1 : end]), head.level))
    title = converted.title or page
    document = Document(f"{edition.id}§{page}", title, POSIX.unit, tuple(sections))
    return Page(page, document, converted)


def installed(edition: Edition = POSIX_2024, home: Path | None = None) -> Path:
    """The directory of an imported edition, or a LibError that says how to import it."""
    root = collection_home("posix", home) / edition.id
    if not (root / INSTALL_RECORD).is_file():
        raise LibError(
            f"POSIX {edition.id} is not imported",
            "",
            f"download {edition.source_url} (personal use, see docs/ieee.md), then run "
            f"primarysource posix import {edition.archive}",
        )
    return root


def pages(volume: str | None = None, *, edition: Edition = POSIX_2024, home: Path | None = None) -> list[str]:
    """Page ids of the imported edition, sorted; only those under `volume` (`functions`) when given."""
    root = installed(edition, home)
    found = [p.relative_to(root).as_posix()[: -len(".html")] for p in root.rglob("*.html")]
    return sorted(p for p in found if volume is None or p.startswith(volume + "/"))


def load_page(page: str, *, edition: Edition = POSIX_2024, home: Path | None = None) -> Page:
    """Read and convert one page, refusing a page id outside the grammar and naming near misses."""
    if not _PAGE.fullmatch(page):
        raise LibError(f"not a POSIX page id: {page!r}", "a page is a path such as functions/open or utilities/pax")
    root = installed(edition, home)
    path = root.joinpath(*page.split("/")).with_name(page.split("/")[-1] + ".html")
    if not path.is_file():
        near = difflib.get_close_matches(page, pages(edition=edition, home=home), n=3)
        raise LibError(f"no page {page!r} in {edition.id}", ("did you mean " + ", ".join(near)) if near else "")
    return parse_page(path.read_bytes(), page, edition)


def cite(page: Page, section: Section | None = None, para: int | str | None = None) -> str:
    """`IEEE Std 1003.1-2024 (The Open Group Base Specifications Issue 8), XSH open, DESCRIPTION ¶2`."""
    volume = VOLUMES.get(page.page.split("/")[0], "")
    where = f"{volume} {page.document.title}".strip()
    out = f"{POSIX_2024.designations[0]} ({POSIX_2024.designations[1]}), {where}"
    if section is not None and section.id:
        out += f", {section.title}"
    return out + (f" ¶{para}" if para is not None else "")


def _ref_text(edition: str, page: str, anchor: str | None, para: int | None = None) -> str:
    return POSIX.grammar.format(Ref(edition, page, para, anchor or None))


def outline(page: str, *, edition: Edition = POSIX_2024, home: Path | None = None) -> str:
    """The page's headings, indented by level, each with the ref that reads it."""
    loaded = load_page(page, edition=edition, home=home)
    heads = [s for s in loaded.document.sections if s.id]
    top = min((s.depth for s in heads), default=1)
    lines = [f"{'  ' * (s.depth - top)}{s.title}  {_ref_text(edition.id, page, s.id)}" for s in heads]
    body = f"{loaded.document.title}  {_ref_text(edition.id, page, None)}\n" + "\n".join(lines)
    return render(body, {"cite": cite(loaded), "unit": POSIX.unit})


def read(ref: str, *, max_tokens: int = 2000, edition: Edition = POSIX_2024, home: Path | None = None) -> str:
    """A page or a section (`#anchor`), from block n with `¶n`, as text with the fixed footer. Long results are
    paged: the `next:` footer is the ref that reads the next page."""
    if "§" not in ref and "::" not in ref and _PAGE.match(ref.strip()):
        ref = f"{edition.id}§{ref.strip()}"  # a bare page (`functions/open#tag_17_372_03`) reads this edition
    parsed = POSIX.grammar.parse(ref)
    if parsed.lines is not None:
        raise LibError(f"{ref!r}: POSIX pages have no line numbers", "use posix-2024§<page>#<anchor>¶<n>")
    if parsed.doc is not None and parsed.doc != edition.id:
        raise LibError(f"{parsed.doc!r} is not imported; this reads {edition.id}", "")
    if parsed.section is None:
        raise LibError(f"{ref!r} names no page", "for example posix-2024§functions/open")
    loaded = load_page(parsed.section, edition=edition, home=home)
    section: Section | None = None
    units: tuple[str, ...] = tuple(loaded.converted.blocks)
    if parsed.anchor is not None:
        section = loaded.section_for(parsed.anchor)
        if section is None:
            anchors = [s.id for s in loaded.document.sections if s.id]
            near = difflib.get_close_matches(parsed.anchor, anchors, n=3)
            hint = ("did you mean " + ", ".join(near)) if near else f"posix_outline {parsed.section} lists them"
            raise LibError(f"no anchor {parsed.anchor!r} on {parsed.section}", hint)
        units = section.units
    if parsed.para is not None and parsed.para > len(units):
        raise LibError(f"{ref!r}: there are {len(units)} blocks here", f"use ¶1 to ¶{len(units)}" if units else "")
    result = budget_page(units, parsed.para or 1, max_tokens)
    body = "\n\n".join(result.units)
    footer = {
        "cite": cite(loaded, section, cursor.para_label(parsed.para, result)),
        "unit": POSIX.unit,
        "span": span_hash(body) if body else "",
        "next": cursor.read_next(_ref_text(edition.id, parsed.section, parsed.anchor), result),
        "warning": "one block is larger than max_tokens" if result.oversize else "",
    }
    return render(body or "(this section has no blocks of its own)", footer)


def _plain(block: str) -> str:
    return re.sub(r"\s+", " ", _html.to_plain(block).replace("*", "")).strip()


def grep(
    needle: str,
    *,
    volume: str | None = None,
    limit: int = 20,
    start: int = 0,
    seconds: float = 10.0,
    edition: Edition = POSIX_2024,
    home: Path | None = None,
) -> str:
    """Pages whose converted text contains `needle`, case-insensitively, one line per matching block.

    Bounded three ways: at most `limit` hits (or every hit of the first page, if it alone has more), at most
    `seconds` of scanning, and a needle of at most 200 characters. A literal, not a pattern, so no input can make
    the scan super-linear. Pages are taken whole, so no hit is skipped: when a bound stops the scan,
    `next: start=<n>` is the 0-based index of the page to resume from, in the order `pages` lists them."""
    wanted = needle.strip().casefold()
    if not wanted or len(wanted) > MAX_NEEDLE:
        raise LibError("grep needs between 1 and 200 characters of text", "")
    limit = max(1, min(limit, MAX_HITS))
    if start < 0:
        raise LibError(f"start is a 0-based page offset, not {start}", "pass the start= value of the last next: line")
    listing = pages(volume, edition=edition, home=home)
    root = installed(edition, home)
    deadline = time.monotonic() + seconds
    hits: list[str] = []
    resume: int | None = None
    for index in range(start, len(listing)):
        if len(hits) >= limit or time.monotonic() > deadline:
            resume = index
            break
        page = listing[index]
        raw = root.joinpath(*page.split("/")).with_name(page.split("/")[-1] + ".html").read_bytes()
        rough = html.unescape(_TAGS.sub("", raw.decode("utf-8", errors="replace")))
        if wanted not in re.sub(r"\s+", " ", rough).casefold():
            continue
        found = _page_hits(parse_page(raw, page, edition), wanted, edition.id)
        if hits and len(hits) + len(found) > limit:
            resume = index
            break
        hits.extend(found)
    body = "\n".join(hits) if hits else f"no block contains {needle!r}"
    footer = {
        "unit": POSIX.unit,
        "next": next_start(resume),
        "warning": f"stopped before page {resume + 1} of {len(listing)}" if resume is not None else "",
    }
    return render(body, footer)


def _page_hits(loaded: Page, wanted: str, edition_id: str) -> list[str]:
    heads = [h for h in loaded.converted.headings if h.kind == "heading"]
    found: list[str] = []
    for index, block in enumerate(loaded.converted.blocks):
        text = _plain(block)
        if wanted not in text.casefold():
            continue
        owner = next((h for h in reversed(heads) if h.block < index), None)
        if owner is None or not owner.anchor:
            ref = _ref_text(edition_id, loaded.page, None, index + 1)
        else:
            ref = _ref_text(edition_id, loaded.page, owner.anchor, index - owner.block)
        at = text.casefold().find(wanted)
        snippet = text[max(0, at - 60) : at + len(wanted) + 60]
        found.append(f"{ref}: {snippet}")
    return found
