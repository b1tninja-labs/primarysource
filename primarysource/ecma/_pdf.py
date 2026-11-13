"""The bbf and ecma collections' PDF model: stored extractions, section lookup and sentence search.

Reading a PDF moved to the core: `extract` is `primarysource.readers.pdf.extract` (`cl.reader_pdf_pypdf`) and the
cutting into sections is `primarysource.readers.bookmarks` (`cl.segment_bookmarks`). They are re-exported here so
the importers, the libraries and their tests are unchanged. The import runs once and its result is stored as
JSON beside the PDF, so serving reads `PdfDocument.from_json` and never needs `pypdf`. A proposal for the core
version of the rest is in `docs/ecma.md`.
"""

from __future__ import annotations

import re
import shutil  # noqa: F401 - tests patch `_pdf.shutil.which` to keep pdftotext out
from collections.abc import Sequence

from primarysource.errors import LibError
from primarysource.readers.bookmarks import cut as _cut
from primarysource.readers.bookmarks import heading_id as _heading_id
from primarysource.readers.bookmarks import slug, split_sentences
from primarysource.readers.pdf import INSTALL_HINT, MAX_BYTES, MAX_OUTLINE, MAX_PAGES, extract

__all__ = [
    "INSTALL_HINT",
    "MAX_BYTES",
    "MAX_OUTLINE",
    "MAX_PAGES",
    "MAX_QUERY_TERMS",
    "PdfDocument",
    "PdfSection",
    "_cut",
    "_heading_id",
    "extract",
    "query_terms",
    "score_units",
    "slug",
    "snippet",
    "split_sentences",
]


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
            raise LibError("the stored extraction is malformed", "", "re-import the document") from exc

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
