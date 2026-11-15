"""Cut the page texts of a GM OBD PDF into citable sections.

GM's files have no bookmarks and no numbered headings: they are tables, one block of pages per module and one
block of rows per DTC or per Mode $06 test. So the sections follow the tables:

- **diagnostic parameter files** (`17OBDG01 Hybrid Diagnostics`): a section per run of pages with the same running
  title (`ecm-summary-tables-initial-dtcs`, `initial-supporting-table-p0011-camposerrorlimic1`), and inside a
  summary-table run a child per DTC (`P0010`). The DTC id repeats across modules; a repeat in one document is
  `P0010-2`, `P0010-3`.
- **Mode $06 references**: a section per monitor heading (`mon-oxygen-sensor-monitor-bank-1-sensor-1`) and inside it
  a child per test row, named `<OBDMID or Test ID>-<TID or Comp ID>` (`01-02`), repeats numbered as above.
- **anything else** (the group summary): a section per page, `p1`, `p2`.

The text is `pdftotext -layout` text, so a table's cells are columns on a line. Rows of a table whose cells wrap are
interleaved, and a Mode $06 row's description can sit on the line above or below its ids: read the section, not
the single line. The text has one added line before each page, `[page N]`, so a citation can name a page.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from primarysource.pdfcorpus.models import Section

_RUNNING = re.compile(r"^\d{2}\s?OBDG\d{2}\b\s*", re.IGNORECASE)
_DTC = re.compile(r"(?:^|\s{2,})(?P<code>[PCBU][0-9A-F]{4})(?=\s{2,}|\s*$)")
_DTC_COLUMN = 45
_MODE6_ROW = re.compile(r"^\s{0,3}(?P<a>[0-9A-F]{2})\s{2,}(?P<b>[0-9A-F]{2})(?=\s|$)")
_MONITOR = re.compile(r"\bMonitors?\b")
_PAGE_MARK = re.compile(r"^\[page \d+\]$")
_SLUG_MAX = 56


@dataclass(frozen=True, slots=True)
class Segmented:
    """The text as the corpus stores it and its sections, with line numbers into that text."""

    lines: list[str]
    sections: list[Section]
    kind: str  # "diagnostics", "mode6" or "pages"


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:_SLUG_MAX].strip("-")
    return out or "section"


def page_title(page: str) -> str:
    """The running title of a page: its first line less the `17 OBDG01` prefix, or the next line when the prefix
    stands alone (a supporting table's own title). Trailing page numbers and columns are cut."""
    rows = [line.strip() for line in page.split("\n") if line.strip()]
    if not rows:
        return ""
    first = _RUNNING.sub("", rows[0]).strip()
    if not first and len(rows) > 1:
        first = rows[1]
    return re.split(r"\s{3,}", first)[0].strip()


class _Ids:
    """Unique ids within one document: a repeat gets `-2`, `-3`."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def take(self, wanted: str) -> str:
        count = self._seen.get(wanted, 0) + 1
        self._seen[wanted] = count
        return wanted if count == 1 else f"{wanted}-{count}"


def layout(pages: Sequence[str]) -> tuple[list[str], list[tuple[int, int]]]:
    """All pages as lines, each page led by `[page N]`; and each page's (first, last) 1-based line numbers."""
    lines: list[str] = []
    spans: list[tuple[int, int]] = []
    for number, page in enumerate(pages, start=1):
        rows = [row.rstrip() for row in page.replace("\r", "").replace("\f", "").split("\n")]
        while rows and not rows[-1]:
            rows.pop()
        first = len(lines) + 1
        lines.append(f"[page {number}]")
        lines.extend(rows)
        spans.append((first, len(lines)))
    return lines, spans


def _diagnostics(pages: Sequence[str], lines: list[str], spans: list[tuple[int, int]]) -> list[Section]:
    ids, codes = _Ids(), _Ids()
    sections: list[Section] = []
    runs: list[tuple[str, int, int]] = []  # title, first page index, last page index
    for index, page in enumerate(pages):
        title = page_title(page) or "untitled"
        if runs and runs[-1][0].casefold() == title.casefold():
            runs[-1] = (runs[-1][0], runs[-1][1], index)
        else:
            runs.append((title, index, index))
    for title, first_page, last_page in runs:
        start, end = spans[first_page][0], spans[last_page][1]
        sections.append(Section(ids.take(slug(title)), title, start, end))
        if "summary table" not in title.casefold():
            continue
        found: list[tuple[int, str]] = []
        for number in range(start, end + 1):
            match = _DTC.search(lines[number - 1])
            if match is not None and match.start("code") < _DTC_COLUMN:
                found.append((number, match["code"]))
        for position, (number, code) in enumerate(found):
            last = found[position + 1][0] - 1 if position + 1 < len(found) else end
            sections.append(Section(codes.take(code), f"{code}, {title}", number, max(number, last)))
    return sections


def _mode6(lines: list[str]) -> list[Section]:
    ids, rows = _Ids(), _Ids()
    starts: list[tuple[int, str, str]] = []  # line, kind ("mon", "row" or "end"), label
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        row = _MODE6_ROW.match(line)
        if row is not None:
            detail = " ".join(line[row.end() :].split())[:60]
            starts.append((number, "row", f"{row['a']}-{row['b']}" + (f" {detail}" if detail else "")))
        elif (
            len(line) - len(line.lstrip()) >= 8
            and "  " not in stripped
            and _MONITOR.search(stripped)
            and not stripped.startswith("Some items")
        ):
            starts.append((number, "mon", stripped))
    rows_seen = [n for n, kind, _ in starts if kind == "row"]
    if rows_seen:
        # The footnotes are the pages after the last page that holds a test row.
        tail = next((n for n in range(rows_seen[-1], len(lines) + 1) if _PAGE_MARK.match(lines[n - 1])), None)
        if tail is not None:
            starts.append((tail, "end", "footnotes"))
            starts.sort(key=lambda item: item[0])
    total = len(lines)
    sections: list[Section] = []
    for position, (number, kind, label) in enumerate(starts):
        if kind == "row":
            following = starts[position + 1][0] if position + 1 < len(starts) else total + 1
            sections.append(Section(rows.take(label.split()[0]), f"test {label}", number, max(number, following - 1)))
            continue
        stop = next((n - 1 for n, k, _ in starts[position + 1 :] if k != "row"), total)
        wanted = f"mon-{slug(label)}" if kind == "mon" else "footnotes"
        sections.append(Section(ids.take(wanted), label, number, max(number, stop)))
    return sections


def segment(pages: Sequence[str], kind: str) -> Segmented:
    """Cut `pages` (one text per page). `kind` is `diagnostics`, `mode6` or `pages`."""
    lines, spans = layout(pages)
    sections: list[Section] = []
    if kind == "diagnostics":
        sections = _diagnostics(pages, lines, spans)
    elif kind == "mode6":
        sections = _mode6(lines)
    if not sections:
        kind = "pages"
        sections = [Section(f"p{n}", f"page {n}", first, last) for n, (first, last) in enumerate(spans, start=1)]
    return Segmented(lines, sections, kind)
