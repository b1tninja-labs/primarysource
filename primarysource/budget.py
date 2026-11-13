"""Token-budgeted paging over units.

rfclib, itulib and zimlore each define `CHARS_PER_TOKEN = 4` and each wrote this loop. The rules they agree on:
a unit is never split, a page always makes progress even when one unit exceeds the budget, and the result says
where to continue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

CHARS_PER_TOKEN = 4


def tokens(text: str) -> int:
    """The estimate all three libraries use: characters divided by four, rounded up."""
    return -(-len(text) // CHARS_PER_TOKEN)


@dataclass(frozen=True, slots=True)
class Page:
    """Units `first..last` (1-based, inclusive) of `total`. `next_start` is None on the last page."""

    units: tuple[str, ...]
    first: int
    last: int
    total: int
    next_start: int | None
    oversize: bool


def page(units: Sequence[str], start: int = 1, max_tokens: int = 2000) -> Page:
    """Take whole units from `start` (1-based) until the next one would exceed `max_tokens`.

    The first unit is always taken, so a caller following `next_start` terminates; `oversize` reports that the
    page went over budget for that reason. A `start` past the end gives an empty page, not an error: the caller
    asked for a position, and "nothing there" is the true answer.
    """
    if start < 1:
        raise ValueError("start is 1-based")
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    total = len(units)
    taken: list[str] = []
    used = 0
    index = start - 1
    while index < total:
        cost = tokens(units[index])
        if taken and used + cost > max_tokens:
            break
        taken.append(units[index])
        used += cost
        index += 1
    last = start + len(taken) - 1
    return Page(
        units=tuple(taken),
        first=start if taken else 0,
        last=last if taken else 0,
        total=total,
        next_start=index + 1 if index < total else None,
        oversize=used > max_tokens,
    )
