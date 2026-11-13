"""Turn a publisher's PDF into numbered sections, using its bookmarks and `pypdf` (the `[bbf]` / `[ecma]` extra).

Private to the bbf and ecma collections. It stands in for the core's `cl.reader_pdf_pypdf` and
`cl.segment_bookmarks` (ROADMAP) and is meant to be replaced by them; a proposal for the core version is in
`docs/ecma.md`. It runs once, at import time, and its result is stored as JSON beside the PDF, so serving never
needs `pypdf`.

What it does, and does not:
- the section list is the PDF's bookmark outline; a bookmark whose title starts with a clause number
  (`5.3 Separator characters`, `A.2.1 Data Types`) or `Annex A` gets that number as its id (`5.3`, `A.2.1`, `A`),
  an `Appendix I` bookmark gets `Appendix-I`, any other (`Bibliography`) its slug;
- page furniture (a header or footer line that repeats on many pages, once digits and Roman numerals are
  ignored) is dropped before anything is cut;
- a section's text runs from its heading to the next bookmark's heading, subsections excluded, and is split
  into sentences, because a PDF gives sentences and not paragraphs (`Unit.SENTENCE`);
- figures, tables and equations are whatever `pypdf` extracts: expect broken columns. The hash a `cite` reports
  is of the text this module produced, and `extractor` in the stored JSON says which `pypdf` produced it.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # noqa: S404 - runs the user's own pdftotext on a PDF whose sha256 is pinned
import unicodedata
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from primarysource.errors import LibError

MAX_BYTES = 64 * 1024 * 1024
MAX_PAGES = 2000
MAX_OUTLINE = 6000
INSTALL_HINT = 'pip install "primarysource[bbf]"  (or [ecma]); both need pypdf'

_NUMBERED = re.compile(r"^(?P<id>\d+(?:\.\d+)*)\.?\s+(?P<title>\S.*)$")
_LETTERED = re.compile(r"^(?P<id>[A-Z](?:\.\d+)+)\.?\s+(?P<title>\S.*)$")
_ANNEX = re.compile(r"^(?:Annex|Appendix)\s+(?P<id>[A-Z0-9]+(?:\.\d+)*)\b[.:]?\s*(?P<title>.*)$", re.IGNORECASE)
_DIGITS = re.compile(r"\d+(?:\s+of\s+\d+)?")
_ROMAN = re.compile(r"^(?:[ivxlcdm]+\s+)|(?:\s+[ivxlcdm]+)$", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'•])")
_ABBREV = ("e.g.", "i.e.", "etc.", "vs.", "cf.", "No.", "Fig.", "Sec.", "approx.")


def slug(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-") or "section"


def split_sentences(text: str) -> list[str]:
    """Sentences of already-flowed text: split after . ! ? before a capital, digit or bracket, not after the
    abbreviations in `_ABBREV`."""
    flowed = " ".join(text.split())
    if not flowed:
        return []
    parts = _SENTENCE_END.split(flowed)
    out: list[str] = []
    for part in parts:
        if out and out[-1].endswith(_ABBREV):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _furniture_key(line: str) -> str:
    key = _DIGITS.sub("#", line.strip())
    key = _ROMAN.sub("", key).strip()
    return re.sub(r"\s+", " ", key)


def _page_of(reader: Any, item: Any) -> int:
    """The 0-based page a bookmark points at, or -1 if its destination is unusable."""
    try:
        return int(reader.get_destination_page_number(item))
    except Exception:  # noqa: BLE001 - pypdf raises many types for a broken destination
        return -1


def _outline(reader: Any) -> list[tuple[str, int, int]]:
    """The bookmark tree flattened to (title, 0-based page, depth), in document order, bounded."""
    flat: list[tuple[str, int, int]] = []

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


def _heading_id(title: str) -> tuple[str, str]:
    for pattern in (_NUMBERED, _LETTERED, _ANNEX):
        match = pattern.match(title)
        if match:
            ident = match.group("id").upper() if pattern is not _NUMBERED else match.group("id")
            if pattern is _ANNEX and title.lower().startswith("appendix"):
                ident = f"Appendix-{ident}"
            return ident, match.group("title").strip() or title
    return slug(title), title


def _cut(pages: list[str], outline: list[tuple[str, int, int]]) -> tuple[list[dict[str, Any]], int]:
    """Cut page texts into sections at the bookmarked headings. Returns the sections and how many headings were
    found as a line of text (the rest fall back to the start of their page)."""
    count = len(pages)
    per_page = [[ln for ln in (" ".join(raw.split()) for raw in text.splitlines()) if ln] for text in pages]
    seen: Counter[str] = Counter()
    for lines in per_page:
        seen.update({_furniture_key(ln) for ln in lines})
    limit = max(3, count // 4)
    cleaned = ["\n".join(ln for ln in lines if seen[_furniture_key(ln)] < limit) for lines in per_page]
    starts: list[int] = []
    joined = ""
    for text in cleaned:
        starts.append(len(joined))
        joined += text + "\n"

    spots: list[tuple[int, int]] = []  # (start, end) of each heading's line in `joined`, never moving backwards
    cursor = 0
    located = 0
    for heading, page, _ in outline:
        ident, text_title = _heading_id(heading)
        numbered = _NUMBERED.match(heading) or _LETTERED.match(heading)
        words = r"\s+".join(re.escape(w) for w in (text_title if numbered else heading).split())
        number = re.escape(ident) if numbered else ""
        pattern = re.compile(rf"(?m)^{number}\.?\s*{words}" if number else rf"(?m)^{words}")
        first = min(page, count - 1)
        base = max(starts[first], cursor)
        found = pattern.search(joined, base, starts[first + 1] if first + 1 < count else len(joined))
        if found is None:
            found = pattern.search(joined, base)
        if found is not None:
            located += 1
        spot = (found.start(), found.end()) if found else (base, base)
        spots.append(spot)
        cursor = max(cursor, spot[0])
    sections: list[dict[str, Any]] = []
    used: Counter[str] = Counter()
    for n, (heading, page, depth) in enumerate(outline):
        ident, text_title = _heading_id(heading)
        used[ident] += 1
        if used[ident] > 1:
            ident = f"{ident}-{used[ident] - 1}"
        begin = spots[n][1]
        stop = spots[n + 1][0] if n + 1 < len(outline) else len(joined)
        sections.append(
            {
                "id": ident,
                "title": text_title,
                "depth": depth,
                "page": page + 1,
                "text": "\n".join(split_sentences(joined[begin : max(begin, stop)])),
            }
        )
    return sections, located


def _pdftotext_pages(path: Path, count: int) -> list[str] | None:
    """The page texts from `pdftotext` (poppler or Xpdf) if it is on PATH and returns `count` pages, else None.
    Its text keeps word spacing that `pypdf` loses on some fonts, and puts headings where they are read."""
    exe = shutil.which("pdftotext")
    if exe is None:
        return None
    try:
        done = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [exe, "-enc", "UTF-8", "-q", str(path), "-"], capture_output=True, timeout=300, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    pages = done.stdout.decode("utf-8", errors="replace").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages if len(pages) == count else None


def extract(data: bytes, path: Path | None = None) -> dict[str, Any]:
    """Read a PDF into `{"title", "pages", "extractor", "sections": [{"id","title","depth","page","text"}]}`.

    `text` is the section's sentences joined by newlines. If `path` names the PDF on disk and `pdftotext` is on
    PATH, its page text is used; otherwise `pypdf`'s, in content-stream order first, and if fewer than 70% of the
    bookmarked headings are found in it as lines (some typesetters emit headings out of order) the pages are
    re-read in `layout` mode and the better result is kept. The bookmarks always come from `pypdf`. Raises
    `LibError` for a PDF that is too large, cannot be read, has no bookmarks, or when `pypdf` is not installed."""
    if len(data) > MAX_BYTES:
        raise LibError(f"PDF is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    try:
        import pypdf
    except ModuleNotFoundError as exc:
        raise LibError("reading a PDF needs pypdf, which is not installed", INSTALL_HINT) from exc
    import io

    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        count = len(reader.pages)
        if count > MAX_PAGES:
            raise LibError(f"PDF has {count} pages, over the {MAX_PAGES} bound", "")
        outline = _outline(reader)
        if not outline:
            raise LibError("the PDF has no bookmarks to split it into sections", "this reader needs a bookmarked PDF")
        meta = reader.metadata
        title = str(meta.title) if meta is not None and meta.title else ""
        external = _pdftotext_pages(path, count) if path is not None else None
        backend = "pdftotext" if external is not None else f"pypdf {pypdf.__version__}"
        if external is not None:
            sections, located = _cut(external, outline)
        else:
            sections, located = _cut([str(reader.pages[i].extract_text() or "") for i in range(count)], outline)
        if external is None and located * 10 < len(outline) * 7:
            layout = [str(reader.pages[i].extract_text(extraction_mode="layout") or "") for i in range(count)]
            better, better_located = _cut(layout, outline)
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
        "extractor": backend,
        "pypdf": pypdf.__version__,
        "headings_found": located,
        "sections": sections,
    }


class PdfSection:
    """One bookmarked section of an extracted PDF: `sentences` are its own text, subsections excluded."""

    __slots__ = ("depth", "id", "page", "sentences", "title")

    def __init__(self, ident: str, title: str, depth: int, page: int, sentences: tuple[str, ...]) -> None:
        self.id, self.title, self.depth, self.page, self.sentences = ident, title, depth, page, sentences


class PdfDocument:
    """An extracted PDF as stored on disk: see `extract` for the fields."""

    def __init__(self, title: str, pages: int, extractor: str, sections: tuple[PdfSection, ...]) -> None:
        self.title, self.pages, self.extractor, self.sections = title, pages, extractor, sections

    @classmethod
    def from_json(cls, raw: object) -> PdfDocument:
        """Validate a stored extraction. A malformed one is a `LibError`: the install is damaged or hostile."""
        try:
            if not isinstance(raw, dict):
                raise TypeError("not an object")
            sections = tuple(
                PdfSection(
                    str(entry["id"]),
                    str(entry["title"]),
                    int(entry["depth"]),
                    int(entry["page"]),
                    tuple(line for line in str(entry["text"]).split("\n") if line),
                )
                for entry in raw["sections"]
            )
            return cls(str(raw.get("title", "")), int(raw["pages"]), str(raw.get("extractor", "")), sections)
        except (AssertionError, KeyError, TypeError, ValueError) as exc:
            raise LibError("the stored extraction is malformed", "re-import the document") from exc

    def find(self, wanted: str) -> tuple[int, str]:
        """Index of the section `wanted` names (its id, else its title's slug, else its title ignoring case),
        and a warning ("" if none). Raises `LibError` with close matches when nothing fits."""
        text = wanted.strip()
        for match in (
            [i for i, s in enumerate(self.sections) if s.id == text],
            [i for i, s in enumerate(self.sections) if s.id.lower() == text.lower()],
            [i for i, s in enumerate(self.sections) if slug(s.title) == slug(text)],
        ):
            if match:
                warning = ""
                if len(match) > 1:
                    warning = f"{len(match)} sections match {text!r}; this is the first"
                return match[0], warning
        import difflib

        close = difflib.get_close_matches(text, [s.id for s in self.sections], n=3, cutoff=0.6)
        raise LibError(f"no section {text!r}", f"did you mean: {', '.join(close)}" if close else "see the outline")

    def span(self, index: int) -> tuple[str, ...]:
        """The section's sentences, then each subsection as a heading unit (`§5.3.1 Title`) followed by its own
        sentences, down to the next section at the same or a shallower depth."""
        root = self.sections[index]
        units = list(root.sentences)
        for sub in self.sections[index + 1 :]:
            if sub.depth <= root.depth:
                break
            units.append(f"§{sub.id} {sub.title}")
            units.extend(sub.sentences)
        return tuple(units)


_TERM = re.compile(r"\w+", re.UNICODE)
MAX_QUERY_TERMS = 16


def query_terms(query: str) -> list[str]:
    """The words of a search query, case-folded, at most `MAX_QUERY_TERMS` of at most 64 characters each."""
    terms = [t for t in _TERM.findall(query.casefold()) if len(t) <= 64]
    if not terms:
        raise LibError("the query has no searchable words", "use words or identifiers, e.g. 'Inform retry'")
    return terms[:MAX_QUERY_TERMS]


def snippet(text: str, terms: list[str], width: int = 160) -> str:
    """About `width` characters of `text` around the first query word."""
    flat = " ".join(text.split())
    low = flat.casefold()
    at = min((i for i in (low.find(t) for t in terms) if i >= 0), default=0)
    begin = max(0, at - 60)
    return ("..." if begin else "") + flat[begin : begin + width] + ("..." if begin + width < len(flat) else "")


def score_units(units: Sequence[str], terms: list[str], title: str, need_all: bool) -> list[tuple[float, int]]:
    """(score, 1-based unit number) for each unit containing every term (or, if not `need_all`, at least half).
    Score: term frequency, plus 3 per distinct term present, plus 2 per term in the section title."""
    found: list[tuple[float, int]] = []
    low_title = title.casefold()
    for number, unit in enumerate(units, start=1):
        if unit.startswith("§"):
            continue  # a subsection heading unit is reached through its own section
        words = _TERM.findall(unit.casefold())
        counts = [words.count(t) for t in terms]
        present = sum(1 for c in counts if c)
        if present == 0 or present * 2 < len(terms) or (need_all and present < len(terms)):
            continue
        found.append((sum(counts) + 3 * present + sum(2 for t in terms if t in low_title), number))
    return found
