"""The two cursors of PLAN.md §5.11 as the plain collections use them.

- A **list** (search, outline, browse, grep, docs) takes a 0-based `start` and prints `next: start=<n>`
  (`render.next_start`), exactly the value to pass back. `window` cuts the page and makes that value.
- A **read** prints `next: <ref>`, a ref string that `read` accepts back: the scope that was read with `¶<n>`
  naming the first unit of the next page. So a `¶n` read starts at unit n and continues, within `max_tokens`,
  to the end of the scope the ref names; one unit alone is what `cite` gives. `read_next` makes that ref.

A whole document is a scope too, and its units are counted the same way, so `doc¶n` continues a document read.
The core grammar refuses `¶` without a section (`refs.RefGrammar`), so `split_doc_para` takes it off first.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from primarysource.budget import Page
from primarysource.errors import LibError
from primarysource.render import next_start

_DOC_PARA = re.compile(r"(?P<head>[^§#¶]+?)\s*¶\s*(?P<para>\d+)\s*")


def window[T](rows: Sequence[T], start: int, limit: int) -> tuple[Sequence[T], str]:
    """Rows `start .. start+limit` (0-based) and the `next:` value: `start=<n>`, or "" on the last page."""
    if start < 0:
        raise LibError(f"start is a 0-based offset, not {start}", "pass the start= value of the last next: line")
    if limit < 1:
        raise LibError(f"limit must be 1 or more, not {limit}", "")
    end = start + limit
    return rows[start:end], next_start(end if end < len(rows) else None)


def split_doc_para(text: str) -> tuple[str, int | None]:
    """`doc¶n` as (`doc`, n); any other text as (text, None), for the collection's own parser to read."""
    if "§" in text or "::" in text or "#" in text:
        return text, None
    match = _DOC_PARA.fullmatch(text)
    if match is None:
        return text, None
    para = int(match["para"])
    if para < 1:
        raise LibError(f"not a ref: {text!r}", "¶ is 1-based")
    return match["head"].strip(), para


def first_unit(para: int | None, total: int, what: str, ref: str) -> int:
    """The 1-based unit a read starts at: `para`, or 1. A `para` past the end is an error naming the range."""
    if para is None:
        return 1
    if para > total:
        raise LibError(f"{ref}: the span has {total} {what}", f"use ¶1 to ¶{total}" if total else "")
    return para


def read_next(scope: str, page: Page) -> str:
    """The `next:` value of a read: `<scope>¶<n>` where the next page starts, or "" when the scope is done."""
    return f"{scope}¶{page.next_start}" if page.next_start is not None else ""


def para_label(para: int | None, page: Page) -> int | str | None:
    """What a read's citation names: None for a whole scope read from its start, `¶n` for one unit, `¶a-b` for a
    page that starts inside the scope or holds several units of a `¶` read."""
    if para is None and (page.first <= 1 or not page.units):
        return None
    if page.first == page.last:
        return page.first
    return f"{page.first}-{page.last}"
