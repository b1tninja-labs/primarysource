"""Read a publisher's PDF into bookmarked sections of sentences (`cl.reader_pdf_pypdf`).

`pypdf` is an ingest-time extra (PLAN.md §5.13): it is imported inside the functions that need it, never at
module level, so a server that answers from stored extractions imports this module without it. Asking for a PDF
read without it is a `LibError` naming the extra, not an `ImportError`.

Lifted from the ecma collection's private reader (`primarysource/ecma/_pdf.py`, now a re-export), with its tests.
The bookmarks always come from `pypdf`; the page text comes from `pdftotext` (poppler or Xpdf) when it is on PATH
and a path to the PDF is given, else from `pypdf`. Backends give different text, so the backend's name and
version are in every extraction (`extractor`) and are what an index puts into its source hash (PLAN.md §4).
Figures, tables and equations are whatever the backend extracts: expect broken columns.

Cutting the page texts into sections is `primarysource.readers.bookmarks` (`cl.segment_bookmarks`).
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess  # noqa: S404 - runs the user's own pdftotext on a PDF whose sha256 the caller pinned
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

from primarysource.errors import LibError
from primarysource.readers.bookmarks import Outline, cut, cut_numbered

MAX_BYTES = 64 * 1024 * 1024
MAX_PAGES = 2000
MAX_OUTLINE = 6000
INSTALL_HINT = 'pip install "primarysource[ecma]"  (or [bbf], [iec], [ieee], [itu], [iso], [msos]); each brings pypdf'

_PDFTOTEXT_VERSION = re.compile(rb"pdftotext\s+version\s+(\S+)", re.IGNORECASE)


class Backend(NamedTuple):
    """The program that produced a text: what an index hashes so a change of backend rebuilds it."""

    name: str
    version: str

    def label(self) -> str:
        """`name version`, the form stored as an extraction's `extractor`."""
        return f"{self.name} {self.version}"


def _pypdf() -> ModuleType:
    try:
        import pypdf
    except ImportError as exc:  # ModuleNotFoundError, or None in sys.modules
        raise LibError("reading a PDF needs pypdf, which is not installed", INSTALL_HINT) from exc
    return pypdf


def pypdf_backend() -> Backend:
    """`pypdf` and its version, or a `LibError` naming the extra when it is not installed."""
    return Backend("pypdf", str(_pypdf().__version__))


def pdftotext_backend() -> Backend | None:
    """`pdftotext` and the version it reports, or None when it is not on PATH. A version it does not report is
    `unknown`."""
    exe = shutil.which("pdftotext")
    if exe is None:
        return None
    try:
        done = subprocess.run([exe, "-v"], capture_output=True, timeout=30, check=False)  # noqa: S603 - fixed argv
    except (OSError, subprocess.SubprocessError):
        return None
    found = _PDFTOTEXT_VERSION.search(done.stderr + b"\n" + done.stdout)
    return Backend("pdftotext", found.group(1).decode("ascii", errors="replace") if found else "unknown")


def _page_of(reader: Any, item: Any) -> int:
    """The 0-based page a bookmark points at, or -1 if its destination is unusable."""
    try:
        return int(reader.get_destination_page_number(item))
    except Exception:  # noqa: BLE001 - pypdf raises many types for a broken destination
        return -1


def outline(reader: Any) -> Outline:
    """A `pypdf.PdfReader`'s bookmark tree flattened to (title, 0-based page, depth), in document order, bounded
    by `MAX_OUTLINE` entries and 12 levels."""
    flat: Outline = []

    def walk(items: Sequence[Any], depth: int) -> None:
        for item in items:
            if len(flat) >= MAX_OUTLINE or depth > 12:
                return
            if isinstance(item, list):
                walk(item, depth + 1)
                continue
            page = _page_of(reader, item)
            title = " ".join(str(item.title).split())
            if title and page >= 0:
                flat.append((title, page, depth))

    walk(reader.outline, 0)
    return flat


def pdftotext_pages(path: Path, count: int, *, layout: bool = False) -> list[str] | None:
    """The page texts from `pdftotext` if it is on PATH and returns `count` pages, else None. Its text keeps word
    spacing that `pypdf` loses on some fonts, and puts headings where they are read. `layout` keeps the page's
    columns (`-layout`), which the numbered-heading splitter reads contents rows and table cells by."""
    exe = shutil.which("pdftotext")
    if exe is None:
        return None
    argv = [exe, *(["-layout"] if layout else []), "-enc", "UTF-8", "-q", str(path), "-"]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=300, check=False)  # noqa: S603 - no shell
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    pages = done.stdout.decode("utf-8", errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages if len(pages) == count else None


def extract(data: bytes, path: Path | None = None, *, numbered: bool = False) -> dict[str, Any]:
    """Read a PDF into `{"title", "pages", "extractor", "pypdf", "headings_found", "sections": [{"id", "title",
    "depth", "page", "text"}]}`.

    `text` is the section's sentences joined by newlines. `extractor` is the backend that gave the page text, as
    `name version` (`Backend.label`); `pypdf` is the version that gave the bookmarks. If `path` names the PDF on
    disk and `pdftotext` is on PATH, its page text is used; otherwise `pypdf`'s, in content-stream order first,
    and if fewer than 70% of the bookmarked headings are found in it as lines (some typesetters emit headings out
    of order) the pages are re-read in `layout` mode and the better result is kept. With `numbered`, a PDF without
    bookmarks is cut at numbered headings instead (`bookmarks.cut_numbered`), and `segmenter` says which was used.
    Raises `LibError` for a PDF that is too large, cannot be read, has no bookmarks (and, with `numbered`, fewer
    than 3 numbered headings), or when `pypdf` is not installed."""
    if len(data) > MAX_BYTES:
        raise LibError(f"PDF is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    pypdf = _pypdf()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        count = len(reader.pages)
        if count > MAX_PAGES:
            raise LibError(f"PDF has {count} pages, over the {MAX_PAGES} bound", "")
        bookmarks = outline(reader)
        if not bookmarks and not numbered:
            raise LibError("the PDF has no bookmarks to split it into sections", "this reader needs a bookmarked PDF")
        meta = reader.metadata
        title = str(meta.title) if meta is not None and meta.title else ""
        external = pdftotext_pages(path, count, layout=not bookmarks) if path is not None else None
        backend = Backend("pypdf", str(pypdf.__version__))
        if not bookmarks:
            if external is not None:
                backend = pdftotext_backend() or Backend("pdftotext", "unknown")
            texts = external
            if texts is None:
                texts = [str(p.extract_text(extraction_mode="layout") or "") for p in reader.pages]
            sections, located = cut_numbered(texts)
            if located < 3:
                raise LibError(
                    "the PDF has no bookmarks, and fewer than 3 numbered headings were found in its text",
                    "this reader needs a bookmarked PDF or numbered clause headings",
                )
        elif external is not None:
            backend = pdftotext_backend() or Backend("pdftotext", "unknown")
            sections, located = cut(external, bookmarks)
        else:
            sections, located = cut([str(reader.pages[i].extract_text() or "") for i in range(count)], bookmarks)
        if bookmarks and external is None and located * 10 < len(bookmarks) * 7:
            layout = [str(reader.pages[i].extract_text(extraction_mode="layout") or "") for i in range(count)]
            better, better_located = cut(layout, bookmarks)
            if better_located > located:
                sections, located = better, better_located
    except LibError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on hostile input
        message = f"could not read the PDF: {type(exc).__name__}: {exc}"
        raise LibError(message, "check the file is the publisher's PDF") from exc
    return {
        "title": title,
        "pages": count,
        "extractor": backend.label(),
        "pypdf": pypdf.__version__,
        "headings_found": located,
        "segmenter": "bookmarks" if bookmarks else "numbered headings",
        "sections": sections,
    }


def _page_title(text: str, number: int) -> str:
    line = next((" ".join(raw.split()) for raw in text.splitlines() if raw.strip()), f"page {number}")
    return line[:80].rstrip()


def extract_pages(data: bytes, path: Path | None = None) -> dict[str, Any]:
    """One section per PDF page, with the same record shape as `extract`.

    For a free joint publication that has no bookmarks and no numbered headings. `pdftotext` supplies the page
    text when it is on PATH and `path` is given; otherwise `pypdf` does."""
    if len(data) > MAX_BYTES:
        raise LibError(f"PDF is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    pypdf = _pypdf()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        count = len(reader.pages)
        if count > MAX_PAGES:
            raise LibError(f"PDF has {count} pages, over the {MAX_PAGES} bound", "")
        if count < 1:
            raise LibError("the PDF has no pages", "")
        meta = reader.metadata
        title = str(meta.title) if meta is not None and meta.title else ""
        external = pdftotext_pages(path, count) if path is not None else None
        backend = Backend("pypdf", str(pypdf.__version__))
        if external is not None:
            texts = external
            backend = pdftotext_backend() or Backend("pdftotext", "unknown")
        else:
            texts = [str(page.extract_text() or "") for page in reader.pages]
    except LibError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on hostile input
        message = f"could not read the PDF: {type(exc).__name__}: {exc}"
        raise LibError(message, "check the file is the publisher's PDF") from exc
    sections = [
        {"id": str(number), "title": _page_title(text, number), "depth": 0, "page": number, "text": text}
        for number, text in enumerate(texts, start=1)
    ]
    return {
        "title": title,
        "pages": count,
        "extractor": backend.label(),
        "pypdf": pypdf.__version__,
        "headings_found": count,
        "segmenter": "pages",
        "sections": sections,
    }
