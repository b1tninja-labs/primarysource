"""The sectioned-document model the libraries share.

A document is an ordered list of sections; a section is an ordered list of units. What a unit IS differs by
corpus and cannot be unified honestly: an RFC has real paragraphs (RFCXML `pn` ids), an extracted PDF clause
only has sentences, a converted HTML article has blocks. So the unit kind is declared, and every result that
hands out a `¶n` ref says which kind `n` counts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum


class Unit(StrEnum):
    """What `¶n` counts within a section."""

    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class Section:
    """One addressable part of a document. `units` are in reading order; `¶1` is `units[0]`."""

    id: str
    title: str
    units: tuple[str, ...] = ()
    depth: int = 1


@dataclass(frozen=True, slots=True)
class Document:
    """A document as the core sees it: an id, a title, the unit kind, and its sections in order."""

    id: str
    title: str
    unit: Unit
    sections: tuple[Section, ...] = field(default=())

    def section(self, section_id: str) -> Section | None:
        """The first section with this id, or None. Duplicate ids are the segmenter's to report."""
        for candidate in self.sections:
            if candidate.id == section_id:
                return candidate
        return None

    def duplicate_ids(self) -> tuple[str, ...]:
        """Section ids that occur more than once, in first-seen order: an ambiguity to warn about."""
        seen: set[str] = set()
        repeated: list[str] = []
        for candidate in self.sections:
            if candidate.id in seen and candidate.id not in repeated:
                repeated.append(candidate.id)
            seen.add(candidate.id)
        return tuple(repeated)


def span_hash(text: str) -> str:
    """`sha256:<16 hex>` of the exact text cited, so a citation can be checked against a later extraction."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
