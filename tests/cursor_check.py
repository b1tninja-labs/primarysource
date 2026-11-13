"""Follow a collection's `next:` cursors to the end, the way a client does (PLAN.md §5.11).

`follow_read` passes each read's `next:` ref back as the ref; `follow_list` passes each list's `next: start=<n>`
back as `start`. Both fail if a cursor repeats, so a page that makes no progress cannot loop forever.
"""

from __future__ import annotations

from collections.abc import Callable

from primarysource.render import FOOTER_ORDER, parse_next_start

_FOOTER_PREFIXES = tuple(f"{key}: " for key in FOOTER_ORDER)


def split(text: str) -> tuple[str, dict[str, str]]:
    """A rendered result as (body, footer)."""
    head, _, tail = text.rstrip("\n").rpartition("\n\n")
    lines = tail.split("\n")
    if head and all(line.startswith(_FOOTER_PREFIXES) for line in lines):
        footer = dict(line.split(": ", 1) for line in lines)
        return head, footer
    return text.rstrip("\n"), {}


def follow_read(read: Callable[[str], str], ref: str, limit: int = 200) -> tuple[list[str], list[str]]:
    """Every page of `ref`, and the refs that read them (the first is `ref`)."""
    bodies: list[str] = []
    refs = [ref]
    while True:
        body, footer = split(read(refs[-1]))
        bodies.append(body)
        nxt = footer.get("next")
        if not nxt:
            return bodies, refs
        assert not nxt.startswith("start="), f"a read's next: is a ref, not {nxt!r}"
        assert nxt not in refs, f"the read cursor repeated: {nxt!r}"
        refs.append(nxt)
        assert len(refs) < limit, "too many pages"


def follow_list(page: Callable[[int], str], limit: int = 200) -> list[str]:
    """The body lines of every page of a list, starting at 0."""
    rows: list[str] = []
    start = 0
    seen = {0}
    while True:
        body, footer = split(page(start))
        rows.extend(body.split("\n"))
        nxt = footer.get("next")
        if not nxt:
            return rows
        start = parse_next_start(nxt)
        assert start not in seen, f"the list cursor repeated: start={start}"
        seen.add(start)
        assert len(seen) < limit, "too many pages"
