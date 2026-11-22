"""What a collection tells the shared local-PDF volume about itself."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from primarysource.model import Unit
from primarysource.readers.pdf import PageTitle
from primarysource.terms import Terms

DOC_PATTERN = r"[0-9A-Za-z][0-9A-Za-z._-]*"
"""A document id as a collection names it (`17OBDG01-hybrid`, `bosch-2.0`)."""
SECTION_PATTERN = r"[0-9A-Za-z][0-9A-Za-z.\-]*"
"""A section: a clause number or slug from the bookmarks (`2.1`, `A`, `bibliography`), or a page (`p12`, `p12-13`)."""


@dataclass(frozen=True, slots=True)
class DocId:
    """What a file is called in the collection: `doc` is the id in refs, `key` the stem of its stored extraction
    (letters, digits, `-`, `_`, `.`), `label` what a citation names it, `title` its own title or empty."""

    doc: str
    key: str
    label: str
    title: str = ""


NameFile = Callable[[str, str], DocId | None]
"""(file name, sha256 of its bytes) -> what the file is, or None for a file the collection does not know."""


@dataclass(frozen=True, slots=True)
class LocalPdfSpec:
    """One collection of the owner's local PDFs.

    `name_file` is the collection's whole identification rule. A file it returns None for is skipped with a note,
    never guessed at. Two files that map to the same `doc` with the same bytes are one document: the importer keeps
    the one whose name has no copy marker (`name (1).pdf`) and records the other as `skipped duplicate of <doc>`.

    Cutting: by default a PDF is cut at its bookmarks, or at numbered headings when it has none. With
    `pages_per_section` the PDF is a table and is cut by page (`readers.bookmarks.cut_pages`); `unit` then says
    what `¶n` counts (a text line is a `Unit.BLOCK`), and `page_title` may name a section better than its first line.
    """

    name: str
    title: str
    terms: Terms
    name_file: NameFile
    instructions: str
    ref_example: str
    unit: Unit = Unit.SENTENCE
    pages_per_section: int | None = None
    page_title: PageTitle | None = None
    clean_text: Callable[[str], str] | None = None
    front_matter: bool = False
    """Keep the text before the first bookmark (a cover, a notice) as a `front-matter` section."""
    """Applied to every extracted section's title and text before they are stored: a collection's fix for a glyph
    its PDFs lose (see `gm`)."""

    def __post_init__(self) -> None:
        if self.terms.collection != self.name:
            raise ValueError(f"the terms of {self.terms.collection!r} cannot gate the {self.name!r} collection")

    @property
    def prefix(self) -> str:
        return f"{self.name}_"

    @property
    def import_command(self) -> str:
        return f"primarysource {self.name} import"

    @property
    def rebuild_command(self) -> str:
        return f"primarysource {self.name} index"

    @property
    def home_variable(self) -> str:
        return f"PRIMARYSOURCE_{self.name.upper()}_HOME"
