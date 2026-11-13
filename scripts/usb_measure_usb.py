"""Measure how well ``split_sections`` parses each USB specification, and write data/usb-split-measure.json.

For every catalogue entry classed ``specification`` the primary PDF is extracted with ``pdftotext -layout`` and
split. The primary PDF is the one with the most extracted text under ``data/raw/<slug>/`` (``pdf/`` for ZIP packages), skipping
redlines, ECNs and adopters agreements. Run from the project root: ``python scripts/measure_usb.py``.
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from primarysource.usb.ingest.extract import ExtractError, extract_text, split_sections  # noqa: E402

DATA = ROOT / "data"
OUT = DATA / "usb-split-measure.json"
_SKIP = re.compile(r"redline|ecn|ecr|adopter|agreement|errata", re.IGNORECASE)
_NEAR_EMPTY_CHARS_PER_PAGE = 200
_MIN_SECTIONS_PER_PAGE = 0.1


def specification_slugs() -> list[str]:
    classification = json.loads(
        (DATA / "usb-classification.json").read_text(encoding="utf-8")
    )
    return [
        e["slug"] for e in classification["entries"] if e["class"] == "specification"
    ]


def _text_length(pdf: Path) -> int:
    try:
        return len(extract_text(pdf))
    except ExtractError:
        return 0


def primary_pdf(slug: str) -> tuple[Path | None, int]:
    """Return (primary PDF, number of PDFs considered) for ``slug``."""
    base = DATA / "raw" / slug
    pdfs = sorted(base.rglob("*.pdf")) if base.is_dir() else []
    preferred = [p for p in pdfs if not _SKIP.search(p.name)] or pdfs
    if not preferred:
        return None, 0
    return max(preferred, key=_text_length), len(pdfs)


def _id_key(sec_id: str) -> tuple[int, ...]:
    """Sort key with appendix letters after every numbered chapter (A -> 1001, B -> 1002)."""
    return tuple(
        int(p) if p.isdigit() else 1000 + ord(p) - 64 for p in sec_id.split(".")
    )


def sequence_errors(ids: list[str]) -> int:
    """Count ids that are not strictly greater than the one before them (document order)."""
    errors = 0
    previous: tuple[int, ...] | None = None
    for sec_id in ids:
        key = _id_key(sec_id)
        if previous is not None and key <= previous:
            errors += 1
        previous = key
    return errors


def measure(slug: str) -> dict:
    pdf, pdf_count = primary_pdf(slug)
    row: dict = {"slug": slug, "pdf": pdf.name if pdf else None, "pdf_count": pdf_count}
    if pdf is None:
        row["error"] = "no pdf on disk"
        return row
    try:
        text = extract_text(pdf)
    except ExtractError as error:
        row["error"] = str(error)
        return row
    pages = text.count("\f")
    sections = split_sections(text)
    lines = text.split("\n")
    row.update(
        pages=pages,
        chars=len(text.strip()),
        section_count=len(sections),
        shallow_sections=sum(1 for s in sections if s.id.count(".") <= 1),
        sequence_errors=sequence_errors([s.id for s in sections]),
        largest_section_lines=max(
            (s.end_line - s.start_line + 1 for s in sections), default=0
        ),
        sample_headings=[
            lines[s.start_line - 1].strip()[:100]
            for s in sections[:: max(1, len(sections) // 3)][:3]
        ],
    )
    return row


def group(row: dict) -> str:
    """Sort one measurement into good, too_few, sequence_errors or extraction_failure."""
    if (
        "error" in row
        or row["chars"] < 2000
        or row["chars"] / max(row["pages"], 1) < _NEAR_EMPTY_CHARS_PER_PAGE
    ):
        return "extraction_failure"
    if row["sequence_errors"]:
        return "sequence_errors"
    if (
        row["section_count"] < 5
        or row["section_count"] < row["pages"] * _MIN_SECTIONS_PER_PAGE
    ):
        return "too_few"
    return "good"


def main() -> int:
    slugs = specification_slugs()
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(measure, slugs))
    for row in rows:
        row["group"] = group(row)
    OUT.write_text(
        json.dumps({"schema": 1, "specs": rows}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({len(rows)} specifications)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
