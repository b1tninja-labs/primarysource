"""Text extraction with ``pdftotext -layout`` and a splitter that finds numbered section headings."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from primarysource.usb.models import Section

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
_CHAPTER = re.compile(r"^\f?\s*Chapter\s+(?P<id>\d+)\.?\s+(?P<heading>[A-Z].*)$")
_CHAPTER_NUMBER_ONLY = re.compile(r"^\f?\s*Chapter\s+(?P<id>\d+)\.?\s*$")
_LEADER = re.compile(r"\.{4,}|(?:\. ){4,}")
# A contents row without a dot leader: "1 Introduction        15", a page number after a run of spaces.
_CONTENTS_ROW = re.compile(r"^\f?\s*(?P<id>\d+)\s+(?P<heading>[A-Z].*?[A-Za-z)])\s{3,}\d+\s*$")
_MAX_HEADING = 120
_MIN_RUNNING_REPEATS = 3


_MARGIN_NUMBER = re.compile(r"^(\f?\s*)\d{1,4}\s{2,}(?=\d+(?:\.\d+)*\.?\s+[A-Z])")


def _strip_margin(line: str) -> str:
    """Drop the margin line number that some specifications print before a dotted heading ("119  2.2.3 Title")."""
    m = _MARGIN_NUMBER.match(line)
    return line if m is None else m.group(1) + line[m.end() :]


def _heading_at(lines: list[str], index: int) -> tuple[str, str] | None:
    """Heading at ``lines[index]``: a ``Chapter N. Title`` line, a ``Chapter N`` line whose title follows, or a numbered line."""
    line = _strip_margin(lines[index])
    m = _CHAPTER.match(line)
    if m is not None:
        return _accept_title(m.group("id"), m.group("heading"))
    m = _CHAPTER_NUMBER_ONLY.match(line)
    if m is not None:
        for following in lines[index + 1 : index + 3]:
            if following.strip():
                return _accept_title(m.group("id"), following.strip())
        return None
    return _match_heading(line)


def _accept_title(sec_id: str, title: str) -> tuple[str, str] | None:
    """A chapter title is accepted when it reads as a title: capitalised, short, and not a table-of-contents row."""
    title = title.strip()
    if _LEADER.search(title) or len(title) > _MAX_HEADING or title.endswith("."):
        return None
    if not title[:1].isupper():
        return None
    return sec_id, title


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


def _running_titles(hits: Iterable[tuple[str, str]]) -> set[str]:
    """Titles that follow a bare number on many lines: page footers and headers such as ``5   Revision 1.0``.

    A chapter title is not repeated behind three different chapter numbers, but a footer is repeated behind
    every page number, and the next page number would otherwise pass as the next chapter.
    """
    counts = Counter(
        heading for sec_id, heading in hits if "." not in sec_id and sec_id.isdigit()
    )
    return {
        heading for heading, count in counts.items() if count >= _MIN_RUNNING_REPEATS
    }


def _counters(found: list[tuple[str, str, int]]) -> dict[str, int]:
    """Rebuild the per-parent counters from the headings accepted so far."""
    last_child: dict[str, int] = {}
    for sec_id, _, _ in found:
        key = _parent_key(sec_id)
        last_child[key] = last_child.get(key, 0) + 1
        last_child.setdefault(sec_id, 0)
    return last_child


def _retract_premature_chapters(found: list[tuple[str, str, int]], sec_id: str) -> bool:
    """Drop trailing chapters that ``sec_id`` proves were false: a list item or footnote read as ``8 Title``.

    When 7.3 turns up after a chapter 8, the 8 cannot have been a heading, or 7.3 would sit under the
    wrong chapter. Only bare chapter numbers are retracted, and only the unbroken run just before ``sec_id``.
    """
    top = _ordinal(sec_id.partition(".")[0]) if sec_id[0].isdigit() else None
    if top is None:
        return False
    dropped = False
    while (
        found
        and "." not in found[-1][0]
        and found[-1][0].isdigit()
        and int(found[-1][0]) > top
    ):
        found.pop()
        dropped = True
    return dropped


def _retract_unexplained_chapters(
    found: list[tuple[str, str, int]], chapter_id: str, explicit: set[int]
) -> bool:
    """Drop trailing bare numbers at or above ``chapter_id`` that were not written as "Chapter N" lines.

    An explicit "Chapter 4. Title" line proves that an earlier bare "4. A Source May ..." list item, which
    arrived first, was not a heading. Only the unbroken run of such bare numbers at the end is dropped.
    """
    number = int(chapter_id)
    dropped = False
    while (
        found
        and "." not in found[-1][0]
        and found[-1][0].isdigit()
        and int(found[-1][0]) >= number
        and found[-1][2] not in explicit
    ):
        found.pop()
        dropped = True
    return dropped


def _contents_entries(lines: list[str]) -> set[tuple[str, str]]:
    """(id, normalised title) of every numbered row of a table of contents.

    A row either ends in a dot leader, or is a number and title followed by a page number after a run of
    spaces, as in the HID Usage Tables contents ("1 Introduction      15").
    """
    entries: set[tuple[str, str]] = set()
    for line in lines:
        leader = _LEADER.search(line)
        if leader is not None:
            m = _NUMBERED.match(line[: leader.start()].rstrip() or "x")
            if m is not None:
                entries.add((m.group("id"), _normal(m.group("heading"))))
            continue
        m = _CONTENTS_ROW.match(line)
        if m is not None:
            entries.add((m.group("id"), _normal(m.group("heading"))))
    return entries


def _normal(title: str) -> str:
    return " ".join(title.split()).casefold()


def _drop_childless_chapters(
    found: list[tuple[str, str, int]], contents: set[tuple[str, str]]
) -> list[tuple[str, str, int]]:
    """Drop runs of two or more consecutive bare chapters that own no ``N.x`` subsection.

    Numbered steps in a test procedure ("4 Verify that the link is up", "5 Reset the port") read exactly like
    chapters but come in runs with no subsection between them. A lone chapter without subsections, such as
    "2 Normative References" between two structured chapters, is kept, and so is any chapter that the document's
    own table of contents lists with the same title. A document in which no chapter has a subsection is left
    alone, since nothing then separates its chapters from its steps.
    """
    with_children = {
        sec_id.partition(".")[0] for sec_id, _, _ in found if "." in sec_id
    }
    if not with_children:
        return found

    def bare(entry: tuple[str, str, int]) -> bool:
        return (
            entry[0].isdigit()
            and entry[0] not in with_children
            and (entry[0], _normal(entry[1])) not in contents
        )

    kept: list[tuple[str, str, int]] = []
    run: list[tuple[str, str, int]] = []
    for entry in [*found, None]:
        if entry is not None and bare(entry):
            run.append(entry)
            continue
        if len(run) < 2:
            kept.extend(run)
        run = []
        if entry is not None:
            kept.append(entry)
    return kept


def _reads_as_prose(title: str) -> bool:
    """True when a heading carries running text or a table row: a sentence break, a mid-line colon, or columns.

    A label that ends in a colon ("Host Key(s):") is a heading, not running text, so it does not count here.
    """
    return ": " in title or ". " in title or "   " in title


def _shallow_chapters(toc_ids: set[str]) -> set[str]:
    """Chapters the contents list without any subsection, in a contents that does list subsections elsewhere.

    When some chapters have their subsections listed and a chapter does not, its subsections are either absent
    or were misread as headings, and a heading under such a chapter must then also read as running text.
    """
    deep = {sec_id.partition(".")[0] for sec_id in toc_ids if "." in sec_id}
    chapters = {sec_id for sec_id in toc_ids if "." not in sec_id}
    return chapters - deep if deep else set()


def split_sections(text: str) -> tuple[Section, ...]:
    """Find numbered headings in ``text`` and return one Section per heading.

    Lines are numbered from 1 and split on newline only, so form feeds do not shift the numbering. Sections
    do not nest: each runs from its heading to the line before the next heading (the last runs to the end).
    A heading is accepted only when it is the next child of a parent already seen (3.2.4 after 3.2.3 inside
    3.2; 2 after 1; B after A). That keeps numbered list items and cross-references that look like headings
    from being read as sections, and it also means one missed heading drops its later siblings.
    """
    lines = text.split("\n")
    toc = _contents_entries(lines)
    toc_ids = {sec_id for sec_id, _ in toc}
    shallow = _shallow_chapters(toc_ids)
    if lines and lines[-1] == "":
        lines.pop()
    hits = [
        (number, _heading_at(lines, number - 1)) for number in range(1, len(lines) + 1)
    ]
    # A "Chapter N" header repeats on every page of its chapter; it is never a footer, so it is exempt
    # from the running-title filter and does not count towards it.
    chapter_lines = {
        number
        for number, line in enumerate(lines, start=1)
        if _CHAPTER.match(line) or _CHAPTER_NUMBER_ONLY.match(line)
    }
    running = _running_titles(
        hit for number, hit in hits if hit is not None and number not in chapter_lines
    )
    found: list[tuple[str, str, int]] = []
    last_child: dict[str, int] = {}
    for number, hit in hits:
        if hit is None:
            continue
        sec_id, heading = hit
        if "." not in sec_id and heading in running and number not in chapter_lines:
            continue
        if "." not in sec_id and number in chapter_lines:
            if _retract_unexplained_chapters(found, sec_id, chapter_lines):
                last_child = _counters(found)
        if (
            "." in sec_id
            and sec_id.partition(".")[0] in shallow
            and sec_id not in toc_ids
            and _reads_as_prose(heading)
        ):
            continue  # a cross-reference or table cell under a chapter the contents shows without subsections
        if not _is_next(sec_id, last_child):
            continue
        if "." in sec_id and _retract_premature_chapters(found, sec_id):
            last_child = _counters(found)
        key = _parent_key(sec_id)
        last_child[key] = last_child.get(key, 0) + 1
        last_child.setdefault(sec_id, 0)
        found.append((sec_id, heading, number))
    found = _drop_childless_chapters(found, toc)
    sections: list[Section] = []
    for index, (sec_id, heading, start) in enumerate(found):
        end = found[index + 1][2] - 1 if index + 1 < len(found) else len(lines)
        sections.append(
            Section(id=sec_id, heading=heading, start_line=start, end_line=end)
        )
    return tuple(sections)
