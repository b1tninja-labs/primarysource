"""The document a reader returns and the store keeps.

Like `primarysource.model.Document` but each section carries an `anchor`, because Markdown, reStructuredText,
AsciiDoc and LaTeX address sections by a label or a slug as well as by position. When the core's `Section` gains
`anchor` (ROADMAP `cl.model_anchor`) this module reduces to a conversion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from primarysource.errors import LibError
from primarysource.model import Unit


@dataclass(frozen=True, slots=True)
class Sec:
    """One addressable part of a document. `id` is an ordinal path (`2.1`); `units` are in reading order and
    `¶1` is `units[0]`. `depth` is the nesting depth, 1 for a top-level section."""

    id: str
    title: str
    depth: int
    anchor: str
    units: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Doc:
    """A document: an id, a title, the unit kind, its sections in order, free-form `meta` (source path, status,
    licence note) and the `warnings` a reader raised about what it could not represent."""

    id: str
    title: str
    unit: Unit
    sections: tuple[Sec, ...] = ()
    meta: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def section(self, section_id: str) -> Sec | None:
        for candidate in self.sections:
            if candidate.id == section_id:
                return candidate
        return None

    def with_meta(self, **more: str) -> Doc:
        return Doc(self.id, self.title, self.unit, self.sections, {**self.meta, **more}, self.warnings)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "unit": self.unit.value,
            "meta": dict(self.meta),
            "warnings": list(self.warnings),
            "sections": [[s.id, s.title, s.depth, s.anchor, list(s.units)] for s in self.sections],
        }

    @staticmethod
    def from_json(data: Mapping[str, Any]) -> Doc:
        try:
            sections = tuple(
                Sec(str(r[0]), str(r[1]), int(r[2]), str(r[3]), tuple(str(u) for u in r[4])) for r in data["sections"]
            )
            return Doc(
                str(data["id"]),
                str(data["title"]),
                Unit(data["unit"]),
                sections,
                {str(k): str(v) for k, v in dict(data["meta"]).items()},
                tuple(str(w) for w in data["warnings"]),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LibError(f"a stored document is damaged ({exc!r})", "import the edition again") from exc
