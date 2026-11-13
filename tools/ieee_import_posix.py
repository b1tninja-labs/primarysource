"""Opt-in measurement, not a test: import a real `susv5.tgz` into a scratch home and print counts only.

    python tools/ieee_import_posix.py <path/to/susv5.tgz> <scratch-home>

The archive is the user's own personal-use download (docs/ieee.md); the scratch home must be outside this
repository. Nothing here prints document text: only numbers, page ids and anchor ids.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

from primarysource.errors import LibError
from primarysource.ieee import posix
from primarysource.ieee.importer import import_posix


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    archive, home = Path(argv[0]), Path(argv[1]).resolve()
    if Path(__file__).resolve().parents[1] in home.parents:
        print("refusing: the scratch home must be outside the repository", file=sys.stderr)
        return 2
    try:
        started = time.perf_counter()
        report = import_posix(archive, home=home)
        imported = time.perf_counter() - started
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 1
    print(f"imported {report.edition}: {report.pages} pages, {report.bytes:,} bytes in {imported:.1f}s")
    print(f"skipped: {dict(sorted(report.skipped.items()))}")
    counts: Counter[str] = Counter()
    started = time.perf_counter()
    for page in posix.pages(home=home):
        loaded = posix.load_page(page, home=home)
        heads = [h for h in loaded.converted.headings if h.kind == "heading"]
        counts["pages"] += 1
        counts["blocks"] += len(loaded.converted.blocks)
        counts["headings"] += len(heads)
        counts["headings without anchor"] += sum(1 for h in heads if not h.anchor)
        counts["pages with duplicate section ids"] += bool(loaded.document.duplicate_ids())
        counts["pages truncated"] += loaded.converted.truncated
        counts["pages without a heading"] += not heads
        counts["volume " + (page.split("/")[0] if "/" in page else "(top)")] += 1
    converted = time.perf_counter() - started
    for key, value in sorted(counts.items()):
        print(f"{key}: {value}")
    print(f"converted every page in {converted:.1f}s")
    started = time.perf_counter()
    hits = posix.grep("file descriptor", limit=200, seconds=60, home=home).count("posix-2024§")
    print(f"grep 'file descriptor': {hits} hits (limit 200) in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
