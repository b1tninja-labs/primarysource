"""Catalogue, fetch and import of the Bluetooth SIG's specifications.

`refresh_catalogue` reads the SIG's listing (one request). `fetch_specs` takes entries from the catalogue and, for
each one not already imported: reads its page (one request) for the PDF address, downloads the PDF (one request),
checks it is a PDF, compares its sha256 with the pin if there is one, stores it as `pdf/<doc_id>.pdf`, extracts and
cuts it at its numbered headings, and records the pin. Requests are paced at the SIG's own `Crawl-delay: 10`
(robots.txt, read 2026-11-15) and go only to bluetooth.com, bluetooth.org and files.bluetooth.com.

**Pins.** `pins.json` records each PDF's sha256 as first fetched. A later fetch of the same document whose bytes
differ is refused (`changed`) unless `repin` is set, because the SIG replaces files in place and a citation should
not silently move. A pin is trust on first use: the catalogue cannot say what the digest should be before a fetch.

The search index is rebuilt once at the end. One document failing (no PDF, a bad download, an unreadable file) is
reported and the rest go on, so a long run can be repeated and resumes where it stopped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource.bluetooth import catalogue
from primarysource.bluetooth.catalogue import Entry
from primarysource.errors import LibError
from primarysource.fetch import Fetcher
from primarysource.fsutil import atomic_write
from primarysource.pdfcorpus import fts
from primarysource.pdfcorpus.corpus import load_corpus
from primarysource.pdfcorpus.index import document_from_dict, sha256_bytes, write_index
from primarysource.pdfcorpus.models import Document, Section
from primarysource.pdfcorpus.pages import read_pages
from primarysource.pdfcorpus.spec import CorpusSpec
from primarysource.pdfcorpus.split import split_sections

CRAWL_DELAY = 10.0
MAX_PAGE = 8 * 1024 * 1024
MAX_PDF = 128 * 1024 * 1024
PINS = "pins.json"
INSTALL_RECORD = "install.json"


@dataclass(frozen=True, slots=True)
class Outcome:
    """One document's result: `status` is `imported`, `unchanged`, `changed`, `no-pdf` or `failed`."""

    slug: str
    status: str
    pages: int = 0
    sections: int = 0
    note: str = ""


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)
    indexed_sections: int = 0
    requests: int = 0


def new_fetcher(transport: Callable[[str, int], bytes] | None = None, interval: float = CRAWL_DELAY) -> Fetcher:
    return Fetcher(catalogue.HOSTS, transport, min_interval=interval, collection="bluetooth")


def refresh_catalogue(home: Path, fetcher: Fetcher) -> list[Entry]:
    """Read the SIG's listing and cache it as `catalogue.json`. Refuses a page that lists nothing."""
    page = fetcher.get(catalogue.LISTING_URL, MAX_PAGE).decode("utf-8", errors="replace")
    listed = catalogue.parse_listing(page)
    if not listed:
        raise LibError(
            "the listing page held no specifications, so its layout has changed",
            "the parser in primarysource/bluetooth/catalogue.py needs updating; nothing was written",
        )
    entries = [*listed, *catalogue.SUPPLEMENTS]
    catalogue.write(home / "catalogue.json", entries)
    return entries


def select(entries: Sequence[Entry], slugs: Sequence[str], status: str = "adopted") -> list[Entry]:
    """The entries named by `slugs` (any status), or all with `status` (`adopted`, `draft`, ... or `any`)."""
    by_slug = {e.slug: e for e in entries}
    if slugs:
        missing = [s for s in slugs if s not in by_slug]
        if missing:
            raise LibError(f"not in the catalogue: {', '.join(missing)}", "primarysource bluetooth list")
        return [by_slug[s] for s in slugs]
    wanted = status.lower()
    return [e for e in entries if wanted == "any" or e.status.lower() == wanted]


def _listed(section_id: str, clauses: Sequence[str]) -> bool:
    return any(section_id == clause or section_id.startswith(f"{clause}.") for clause in clauses)


def _with_located(lines: list[str], sections: list[Section], located: Sequence[tuple[str, str]]) -> list[Section]:
    """The splitter's sections with each `(clause, heading)` the splitter missed added, found by its exact line.

    A heading line is the clause number and title, optionally followed by a table's "UUID" column label, and nothing
    else, so a contents row (which has leaders and a page number) cannot match. Each section runs to the line before
    the next heading.
    """
    starts = [(s.start_line, s.id, s.heading) for s in sections]
    known = {s.id for s in sections}
    for clause, title in located:
        if clause in known:
            continue
        pattern = re.compile(rf"^\s*{re.escape(clause)}\s+{re.escape(title)}(?:\s+UUID)?\s*$")
        hit = next((n for n, line in enumerate(lines, start=1) if pattern.match(line)), None)
        if hit is None:
            raise LibError(
                f"the heading '{clause} {title}' is not in the PDF",
                "the AN_LOCATED list in primarysource/bluetooth/catalogue.py does not match this edition; "
                "nothing was written",
            )
        starts.append((hit, clause, title))
    starts.sort()
    return [
        Section(sec_id, heading, start, starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines))
        for i, (start, sec_id, heading) in enumerate(starts)
    ]


def _cut(
    pages: list[str], clauses: Sequence[str] = (), located: Sequence[tuple[str, str]] = ()
) -> tuple[list[str], list[Section], int]:
    """The document's text and sections, and how many sections were left out.

    With `clauses`, only those clauses (and their subsections) are kept: the text is rebuilt from their lines alone,
    so what was left out is not in the corpus at all, not merely unindexed.
    """
    text = "\n".join(pages)
    lines = text.split("\n")
    found = split_sections(text)
    seen: set[str] = set()
    sections: list[Section] = []
    for section in found:
        if section.id not in seen and section.end_line <= len(lines):
            seen.add(section.id)
            sections.append(section)
    if clauses:
        sections = _with_located(lines, sections, located)
        kept = [s for s in sections if _listed(s.id, clauses)]
        if not kept:
            raise LibError(
                "none of the clauses this collection keeps was found in the PDF's headings",
                "the clauses in primarysource/bluetooth/catalogue.py do not match this edition; nothing was written",
            )
        keep_lines = sorted({n for s in kept for n in range(s.start_line, s.end_line + 1)})
        index = {old: new for new, old in enumerate(keep_lines, start=1)}
        cut = [Section(s.id, s.heading, index[s.start_line], index[s.end_line]) for s in kept]
        return [lines[n - 1] for n in keep_lines], cut, len(sections) - len(kept)
    if not sections:
        first = 1
        for number, page in enumerate(pages, start=1):
            last = first + page.count("\n")
            sections.append(Section(f"p{number}", f"page {number}", first, max(first, last)))
            first = last + 1
    return lines, sections, 0


def _json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return loaded if isinstance(loaded, dict) else default


def fetch_specs(
    spec: CorpusSpec,
    entries: Sequence[Entry],
    fetcher: Fetcher,
    *,
    home: Path,
    root: Path | None = None,
    force: bool = False,
    repin: bool = False,
    progress: Callable[[Outcome], None] | None = None,
) -> Report:
    """Fetch and import `entries`, then rebuild the search index. See the module docstring."""
    root = spec.corpus_dir() if root is None else root
    pins = _json(home / PINS, {})
    record = _json(root / INSTALL_RECORD, {"documents": {}})
    record.setdefault("documents", {})
    try:
        raw = json.loads((root / "index.json").read_text(encoding="utf-8"))
        documents = {d.doc_id: d for d in (document_from_dict(x) for x in raw["documents"])}
    except (OSError, ValueError, KeyError, TypeError):
        documents = {}
    (root / "text").mkdir(parents=True, exist_ok=True)
    (home / "pdf").mkdir(parents=True, exist_ok=True)
    report = Report()
    changed = False

    def done(outcome: Outcome) -> None:
        report.outcomes.append(outcome)
        if progress is not None:
            progress(outcome)

    for entry in entries:
        known = documents.get(entry.slug)
        if known is not None and not force and (root / known.text_file).is_file():
            done(Outcome(entry.slug, "unchanged", sections=len(known.sections)))
            continue
        try:
            if entry.pdf:
                pdf_url: str | None = entry.pdf
            else:
                pdf_url = catalogue.parse_spec_page(
                    fetcher.get(entry.page, MAX_PAGE).decode("utf-8", errors="replace")
                )
            if pdf_url is None:
                done(Outcome(entry.slug, "no-pdf", note="its page offers no PDF (HTML only)"))
                continue
            data = fetcher.get(pdf_url, MAX_PDF)
            if not data.startswith(b"%PDF-"):
                # files.bluetooth.com puts a "your download starts automatically" page in front of the file.
                link = catalogue.parse_download_page(data[:MAX_PAGE].decode("utf-8", errors="replace"))
                if link is not None:
                    data = fetcher.get(link, MAX_PDF)
            if not data.startswith(b"%PDF-"):
                raise LibError(
                    f"{pdf_url} is not a PDF", "the SIG may have changed its download; nothing was written"
                )
            digest = sha256_bytes(data)
            pinned = pins.get(entry.slug, {}).get("sha256")
            if pinned and pinned != digest and not repin:
                done(
                    Outcome(
                        entry.slug,
                        "changed",
                        note=f"the PDF changed since it was pinned ({pinned[:12]} -> {digest[:12]}); use --repin",
                    )
                )
                continue
            pdf_path = home / "pdf" / f"{entry.slug}.pdf"
            atomic_write(pdf_path, data)
            pages, extractor, created = read_pages(pdf_path)
            lines, sections, left_out = _cut(pages, entry.clauses, entry.located)
            text_file = f"text/{entry.slug}.txt"
            atomic_write(root / text_file, ("\n".join(lines) + "\n").encode("utf-8"))
            documents[entry.slug] = Document(
                doc_id=entry.slug,
                number=entry.number,
                title=entry.title,
                date=created or "unknown",
                status=entry.corpus_status,
                url=entry.page,
                sha256=digest,
                text_file=text_file,
                sections=tuple(sections),
            )
            now = datetime.now(UTC).isoformat(timespec="seconds")
            pins[entry.slug] = {"sha256": digest, "bytes": len(data), "source": pdf_url, "pinned": now}
            record["documents"][entry.slug] = {
                "version": entry.revision,
                "source": pdf_url,
                "pages": len(pages),
                "extractor": extractor,
                "sections": len(sections),
                "segmenter": "numbered headings" if sections and not sections[0].id.startswith("p") else "pages",
                "clauses": list(entry.clauses),
                "sections_left_out": left_out,
                "imported": now,
            }
            changed = True
            # Written as it goes, so an interrupted run keeps what it fetched.
            atomic_write(home / PINS, (json.dumps(pins, indent=1) + "\n").encode("utf-8"))
            write_index(root / "index.json", sorted(documents.values(), key=lambda d: d.doc_id))
            atomic_write(root / INSTALL_RECORD, (json.dumps(record, indent=1) + "\n").encode("utf-8"))
            done(
                Outcome(
                    entry.slug, "imported", len(pages), len(sections), record["documents"][entry.slug]["segmenter"]
                )
            )
        except LibError as exc:
            done(Outcome(entry.slug, "failed", note=f"{exc.message} ({exc.hint})" if exc.hint else exc.message))
    report.requests = fetcher.requests
    if changed:
        report.indexed_sections = fts.build(load_corpus(spec, root))
    return report
