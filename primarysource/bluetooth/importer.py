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
    entries = catalogue.parse_listing(page)
    if not entries:
        raise LibError(
            "the listing page held no specifications, so its layout has changed",
            "the parser in primarysource/bluetooth/catalogue.py needs updating; nothing was written",
        )
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


def _cut(pages: list[str]) -> tuple[list[str], list[Section]]:
    text = "\n".join(pages)
    lines = text.split("\n")
    found = split_sections(text)
    seen: set[str] = set()
    sections: list[Section] = []
    for section in found:
        if section.id not in seen and section.end_line <= len(lines):
            seen.add(section.id)
            sections.append(section)
    if not sections:
        first = 1
        for number, page in enumerate(pages, start=1):
            last = first + page.count("\n")
            sections.append(Section(f"p{number}", f"page {number}", first, max(first, last)))
            first = last + 1
    return lines, sections


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
            pdf_url = catalogue.parse_spec_page(fetcher.get(entry.page, MAX_PAGE).decode("utf-8", errors="replace"))
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
            lines, sections = _cut(pages)
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
                "pages": len(pages),
                "extractor": extractor,
                "sections": len(sections),
                "segmenter": "numbered headings" if sections and not sections[0].id.startswith("p") else "pages",
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
