"""Whether the edition being read is the latest one the collection already records.

A collection passes the editions of one work from its own catalogue. This module does not look a publisher up,
and it does not decide that a later document rewrites a section. A later edition is another document. An
amendment or erratum listed beside the edition is named, and it is not part of the text being read.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from primarysource.errors import LibError


@dataclass(frozen=True, slots=True)
class Edition:
    """One recorded edition. `order` is higher for a later edition. `current` is the catalogue's own mark."""

    ref: str
    order: int
    current: bool = True
    imported: bool = True


@dataclass(frozen=True, slots=True)
class Aside:
    """A correction or amendment the catalogue lists beside an edition, as its own document."""

    ref: str


def join(*parts: str) -> str:
    """The warning footer is one line. Empty parts drop out."""
    return "; ".join(part for part in parts if part)


def notes(rows: Iterable[tuple[str, str]]) -> list[str]:
    """One line per document that has a standing sentence, in the order the documents were seen.

    A search page uses this so the later edition is named once, beside the hits, without repeating it on
    every section of the same document.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for ref, text in rows:
        if not text or ref in seen:
            continue
        seen.add(ref)
        lines.append(f"{ref}: {text}")
    return lines


def warning(reading: Edition, family: Sequence[Edition], asides: Sequence[Aside] = ()) -> str:
    """The sentence for the `warning:` line, or empty when this edition is the latest recorded one.

    A later edition that is not imported is still named. Silence means the catalogue records nothing later,
    which is not the same as a publisher promising there is nothing later.
    """
    others = [item for item in family if item.ref != reading.ref]
    later = [item for item in others if item.current and item.order > reading.order]
    current = [item for item in others if item.current]
    parts: list[str] = []
    if not reading.current:
        if current:
            best = max(current, key=lambda item: item.order)
            parts.append(f"this edition is not current; current text: {_name(best)}")
        else:
            parts.append("this edition is not current")
    elif later:
        best = max(later, key=lambda item: item.order)
        parts.append(f"a later edition is recorded: {_name(best)}")
    if asides:
        parts.append("separate text, not applied to this edition: " + ", ".join(item.ref for item in asides))
    return join(*parts)


def _name(item: Edition) -> str:
    return item.ref if item.imported else f"{item.ref} (not imported)"


def dated_family(
    doc: str,
    keys: Iterable[str],
    split: Callable[[str], tuple[str, str | None]],
    prefix: str,
) -> str:
    """Later imported years of the same number, from document ids the collection already stored.

    An id is `<number>@<year>` or `<number>@<year>+<supplement>`. A supplement is named when the year being
    read has one, and the text being read says so when it is the supplement. A year the collection has not
    imported is absent here.
    """
    try:
        number, rest = split(doc)
    except LibError:
        return ""
    if rest is None:
        return ""
    year_text, _, supplement = rest.partition("+")
    if not year_text.isdigit():
        return ""
    year = int(year_text)
    family: list[Edition] = []
    asides: list[Aside] = []
    for key in keys:
        try:
            other_number, other_rest = split(str(key))
        except LibError:
            continue
        if other_number != number or other_rest is None:
            continue
        other_year, _, other_supplement = other_rest.partition("+")
        if not other_year.isdigit():
            continue
        if other_supplement:
            if int(other_year) == year and str(key) != doc:
                asides.append(Aside(f"{prefix}:{key}"))
            continue
        family.append(Edition(f"{prefix}:{key}", int(other_year)))
    text = warning(Edition(f"{prefix}:{number}@{year_text}", year), family, asides)
    if supplement:
        text = join(f"supplement of {prefix}:{number}@{year_text}", text)
    return text
