"""How faithfully does the converter treat every HTML article of a real ZIM?

Not part of the test suite (it needs a downloaded ZIM). Prints, per ZIM: articles converted, exceptions,
articles that came out empty, source bytes against markdown bytes, leftover `data:` URIs, and the three
structure counts the converter exists to preserve - `<pre>` blocks against code fences, `<table>` against pipe
tables, and headings.

    python scripts/measure_conversion.py path/to/a.zim [more.zim ...]

A fence count equal to the non-empty `<pre>` count and zero leftover data URIs are the pass conditions; the rest
are numbers to read, not thresholds.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from zimlore import library
from zimlore.markdown import convert


def measure(path: Path) -> dict[str, object]:
    archive = library.open_archive(path)
    book = library.read_book(path)
    stats = {"articles": 0, "errors": 0, "empty": 0, "src": 0, "md": 0, "data_uri": 0}
    pre = fences = tables = pipe_tables = headings = 0
    started = time.perf_counter()
    for index in range(archive.entry_count):
        entry = archive.get_entry_by_id(index)
        if entry.is_redirect or str(entry.get_item().mimetype).split(";")[0] != "text/html":
            continue
        html = bytes(entry.get_item().content).decode("utf-8", errors="replace")
        stats["articles"] += 1
        stats["src"] += len(html)
        try:
            doc = convert(html, str(entry.path))
        except Exception:  # noqa: BLE001 - the point is to count them
            stats["errors"] += 1
            continue
        text = doc.markdown
        stats["md"] += len(text)
        stats["empty"] += not doc.blocks
        stats["data_uri"] += len(re.findall(r"data:[a-z]+/[a-z0-9.+-]+;base64", text))
        # <pre> inside <script> (rustdoc's search-index JSON, inline templates) is data, not a code block; counting it
        # gave false shortfalls on rustdoc ZIMs. Tags are matched case-insensitively (javadoc 1.6 writes <PRE>).
        visible = re.sub(r"<script\b.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
        pre += len(re.findall(r"<pre\b[^>]*>(?!\s*</pre>)", visible, flags=re.IGNORECASE))
        fences += sum(1 for block in doc.blocks if block.lstrip("> ").startswith("```"))
        tables += len(re.findall(r"<table\b", visible, flags=re.IGNORECASE))
        pipe_tables += sum(1 for block in doc.blocks if block.startswith("| "))
        headings += len(doc.headings)
    stats["seconds"] = round(time.perf_counter() - started, 2)
    return {
        "zim": f"{book.name} {book.date}",
        **stats,
        "pre": pre,
        "fences": fences,
        "tables": tables,
        "pipe_tables": pipe_tables,
        "headings": headings,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for name in sys.argv[1:]:
        print(measure(Path(name)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
