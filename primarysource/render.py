"""The text shape of a tool result: body first, then footer lines in one fixed order.

Decision recorded in PLAN.md: results are text, because the passage dominates the tokens and a JSON string
escapes every newline in it. What a JSON result carried as fields is carried as `key: value` footer lines, in
the order below, so a reader (or a regex) finds them in the same place in every library.
"""

from __future__ import annotations

from collections.abc import Mapping

FOOTER_ORDER = ("cite", "unit", "span", "next", "relaxed", "warning")


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
