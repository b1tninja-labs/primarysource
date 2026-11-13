"""What every reader needs: strict decoding, slugs and the section builder."""

from __future__ import annotations

import re
import unicodedata

from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.pkgdocs.model import Doc, Sec

_SLUG_DROP = re.compile(r"[^\w\- ]", re.UNICODE)


def decode(data: bytes, what: str) -> str:
    """UTF-8 text with line endings normalised to `\\n`. A NUL byte or invalid UTF-8 is an error, never a guess:
    a reader that substituted characters would quietly change what a citation says."""
    if b"\x00" in data:
        raise LibError(f"{what} contains a NUL byte; it is not text", "check that the source is the expected file")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise LibError(
            f"{what} is not valid UTF-8 ({exc.reason} at byte {exc.start})",
            "the collection reads UTF-8 sources only; report the file rather than converting it",
        ) from exc
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


_ROLE = re.compile(r":[A-Za-z][\w:+.-]*:`([^`]*)`")


def clean_title(title: str) -> str:
    """A heading as plain text: RST roles and inline-literal backticks removed, whitespace collapsed."""
    return " ".join(_ROLE.sub(chr(92) + "1", title).replace("`", "").split())


def slugify(title: str) -> str:
    """GitHub's heading slug: lowercase, punctuation dropped, spaces to hyphens. This is the rule used here, not
    a claim that any specification defines it."""
    text = unicodedata.normalize("NFKC", title).strip().lower()
    return _SLUG_DROP.sub("", text).replace(" ", "-")


class Builder:
    """Collects headings and units into sections with ordinal-path ids and unique anchors.

    `heading(level, ...)` takes the format's own level; levels may skip (h1 to h3) and ids follow the nesting
    actually seen, so a skipped level does not leave a gap in the path. Text before the first heading goes in
    section `0` titled with the document title. With `base="5"` the document is one numbered unit of a larger
    work (a chapter): `root()` opens section `5` and every later heading is `5.<n>`.
    """

    def __init__(self, base: str = "") -> None:
        self._base = base
        self._ids: list[str] = []
        self._titles: list[str] = []
        self._depths: list[int] = []
        self._anchors_of: list[str] = []
        self._units: list[list[str]] = []
        self._stack: list[int] = []  # levels of the open sections
        self._counts: list[int] = []
        self._used: set[str] = set()
        self._current: list[str] | None = None
        self._preamble_title = ""
        self._rooted = False

    def set_preamble_title(self, title: str) -> None:
        self._preamble_title = title

    def _unique(self, anchor: str) -> str:
        if not anchor:
            anchor = "section"
        candidate, n = anchor, 0
        while candidate in self._used:
            n += 1
            candidate = f"{anchor}-{n}"
        self._used.add(candidate)
        return candidate

    def _open(self, section_id: str, title: str, depth: int, anchor: str) -> None:
        units: list[str] = []
        self._ids.append(section_id)
        self._titles.append(title)
        self._depths.append(depth)
        self._anchors_of.append(self._unique(anchor))
        self._units.append(units)
        self._current = units

    def root(self, title: str, anchor: str = "") -> None:
        """Open the numbered root section (`base`, or `0`) with the document's own title."""
        self._rooted = True
        self._stack = []
        title = clean_title(title)
        self._open(self._base or "0", title, 1, anchor or slugify(title))

    def heading(self, level: int, title: str, anchor: str = "") -> None:
        title = clean_title(title)
        while self._stack and self._stack[-1] >= level:
            self._stack.pop()
        depth = len(self._stack) + 1
        del self._counts[depth:]
        while len(self._counts) < depth:
            self._counts.append(0)
        self._counts[depth - 1] += 1
        path = ".".join(str(n) for n in self._counts[:depth])
        section_id = f"{self._base}.{path}" if self._base else path
        self._stack.append(level)
        self._open(section_id, title, depth + (1 if self._rooted else 0), anchor or slugify(title))

    def unit(self, text: str) -> None:
        if not text.strip():
            return
        if self._current is None:
            self._open(self._base or "0", self._preamble_title, 1, slugify(self._preamble_title) or "preamble")
        if self._current is not None:
            self._current.append(text)

    def sections(self) -> tuple[Sec, ...]:
        return tuple(
            Sec(i, t, d, a, tuple(u))
            for i, t, d, a, u in zip(
                self._ids, self._titles, self._depths, self._anchors_of, self._units, strict=True
            )
        )

    def doc(self, doc_id: str, title: str, *, unit: Unit = Unit.BLOCK, warnings: tuple[str, ...] = ()) -> Doc:
        sections = self.sections()
        if sections and not sections[0].title:
            first = sections[0]
            sections = (Sec(first.id, title or doc_id, first.depth, first.anchor, first.units), *sections[1:])
        return Doc(doc_id, title or doc_id, unit, sections, {}, warnings)
