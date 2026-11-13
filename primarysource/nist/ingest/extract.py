"""Text extraction with ``pdftotext -layout`` and a splitter that finds numbered section headings."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from primarysource.nist.models import Section

MISSING_MESSAGE = (
    "pdftotext was not found on PATH. Install poppler-utils (on MSYS2: pacman -S mingw-w64-x86_64-poppler) "
    "and make sure pdftotext is on PATH."
)


class ExtractError(RuntimeError):
    """Raised when text extraction cannot run or fails."""


def find_pdftotext() -> str:
    """Return the path of pdftotext, or raise ExtractError saying how to get it."""
    found = shutil.which("pdftotext")
    if found is None:
        raise ExtractError(MISSING_MESSAGE)
    return found


def extract_text(pdf: Path, *, timeout: float = 300.0) -> str:
    """Run ``pdftotext -layout`` on ``pdf`` and return the text (pages separated by form feeds)."""
    exe = find_pdftotext()
    try:
        result = subprocess.run(  # noqa: S603
            [exe, "-layout", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ExtractError(
            f"pdftotext timed out after {timeout:.0f}s on {pdf}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ExtractError(
            f"pdftotext failed on {pdf} (exit {result.returncode}): {detail}"
        )
    return result.stdout.decode("utf-8", "replace")


# "Appendix A. Title" -> id "A";  "A.4.1. Title" -> id "A.4.1";  "3.2.4. Title" or "3.2.4 Title" -> id "3.2.4".
# The title may follow the id without a space ("A.5.1.1.1GENERAL ...") when pdftotext loses the gap.
_APPENDIX = re.compile(r"^\f?\s*Appendix\s+(?P<id>[A-Z])\.\s+(?P<heading>\S.*)$")
_LETTERED = re.compile(r"^\f?\s*(?P<id>[A-Z](?:\.\d+)+)\.?\s*(?P<heading>[A-Z].*)$")
_NUMBERED = re.compile(
    r"^\f?\s*(?P<id>\d+(?:\.\d+)*)(?P<dot>\.?)\s*(?P<heading>[A-Z].*)$"
)
_LEADER = re.compile(r"\.{4,}|(?:\. ){4,}")
_MAX_HEADING = 120


def _match_heading(line: str) -> tuple[str, str] | None:
    """Return (id, heading) when ``line`` looks like a section heading, else None."""
    for pattern in (_APPENDIX, _LETTERED, _NUMBERED):
        m = pattern.match(line)
        if m is None:
            continue
        heading = m.group("heading").strip()
        if pattern is _NUMBERED and not m.group("dot") and "." not in m.group("id"):
            # A bare chapter number ("3 CCID Functional ...") is a heading only when it reads as one: a
            # table row has runs of spaces between columns, and a wrapped note has an unclosed bracket.
            if "  " in heading or heading.count("(") != heading.count(")"):
                return None
        if (
            _LEADER.search(heading)
            or len(heading) > _MAX_HEADING
            or heading.endswith(".")
        ):
            return None  # table-of-contents row or running prose
        return m.group("id"), heading
    return None


def _ordinal(part: str) -> int:
    return int(part) if part.isdigit() else ord(part) - ord("A") + 1


def _parent_key(sec_id: str) -> str:
    """Key of the counter ``sec_id`` belongs to: its parent id, or one of two top-level sequences."""
    parent, _, _ = sec_id.rpartition(".")
    if parent:
        return parent
    return "#appendix" if sec_id.isalpha() else "#chapter"


def _is_next(sec_id: str, last_child: dict[str, int]) -> bool:
    """True when ``sec_id`` is the next child of a parent already seen (``1`` and ``A`` open the top levels)."""
    key = _parent_key(sec_id)
    if key not in last_child and not key.startswith("#"):
        return False
    return _ordinal(sec_id.rpartition(".")[2]) == last_child.get(key, 0) + 1


def split_sections(text: str) -> tuple[Section, ...]:
    """Find numbered headings in ``text`` and return one Section per heading.

    Lines are numbered from 1 and split on newline only, so form feeds do not shift the numbering. Sections
    do not nest: each runs from its heading to the line before the next heading (the last runs to the end).
    A heading is accepted only when it is the next child of a parent already seen (3.2.4 after 3.2.3 inside
    3.2; 2 after 1; B after A). That keeps numbered list items and cross-references that look like headings
    from being read as sections, and it also means one missed heading drops its later siblings.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    found: list[tuple[str, str, int]] = []
    last_child: dict[str, int] = {}
    for number, line in enumerate(lines, start=1):
        hit = _match_heading(line)
        if hit is None:
            continue
        sec_id, heading = hit
        if not _is_next(sec_id, last_child):
            continue
        key = _parent_key(sec_id)
        last_child[key] = last_child.get(key, 0) + 1
        last_child.setdefault(sec_id, 0)
        found.append((sec_id, heading, number))
    sections: list[Section] = []
    for index, (sec_id, heading, start) in enumerate(found):
        end = found[index + 1][2] - 1 if index + 1 < len(found) else len(lines)
        sections.append(
            Section(id=sec_id, heading=heading, start_line=start, end_line=end)
        )
    return tuple(sections)
