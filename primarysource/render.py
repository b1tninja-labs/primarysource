"""The text shape of a tool result: body first, then footer lines in one fixed order.

Decision recorded in PLAN.md: results are text, because the passage dominates the tokens and a JSON string
escapes every newline in it. What a JSON result carried as fields is carried as `key: value` footer lines, in
the order below, so a reader (or a regex) finds them in the same place in every library.

The `next:` value is exactly what to pass back (PLAN.md §5.11): a ref string for a read, which `read` accepts as
its `ref`, and `start=<n>` for a list (search, outline, browse, grep), a 0-based offset for the same tool's
`start` argument. `next_start` and `parse_next_start` are the two halves of the list cursor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

FOOTER_ORDER = ("cite", "unit", "span", "next", "relaxed", "confidence", "warning")

_NEXT_START = re.compile(r"start=(0|[1-9][0-9]*)")


def render(body: str, footer: Mapping[str, str]) -> str:
    """Body, a blank line, then the known footer keys in FOOTER_ORDER. Unknown keys are a bug, not output."""
    unknown = sorted(set(footer) - set(FOOTER_ORDER))
    if unknown:
        raise ValueError(f"unknown footer keys: {', '.join(unknown)}")
    lines = [f"{key}: {footer[key]}" for key in FOOTER_ORDER if footer.get(key)]
    for line in lines:
        if "\n" in line:
            raise ValueError("a footer value must be one line")
    return body.rstrip("\n") + ("\n\n" + "\n".join(lines) if lines else "") + "\n"


def next_start(offset: int | None) -> str:
    """The `next:` value of a list page that continues at the 0-based `offset`: `start=<offset>`. None (the last
    page) gives "", which `render` drops, so a footer with no `next:` line means there is nothing more."""
    if offset is None:
        return ""
    if offset < 0:
        raise ValueError("a list cursor is a 0-based offset")
    return f"start={offset}"


def parse_next_start(value: str) -> int:
    """The offset in a list `next:` value, the inverse of `next_start`. Anything else is a bug in the caller."""
    match = _NEXT_START.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"not a list cursor: {value!r} (expected 'start=<n>')")
    return int(match[1])
