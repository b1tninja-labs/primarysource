"""Heuristic section chunking for RFC .txt documents.

RFC txt files have a predictable structure: numbered headings (up to 4
levels) indented 0-5 spaces with two spaces before the title, dot-leader
table-of-contents entries, repeated page headers/footers and page breaks.
We detect real headings (excluding TOC leaders and renumbered inline
lists), cut sections until the next heading, strip page furniture, and
split oversized sections into paragraph-boundary parts.

Line ranges refer to the ORIGINAL file lines so an agent can re-read the
exact window with get_rfc(doc, start_line=..., max_lines=...).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_HEADING = re.compile(r"^ {0,7}(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+(\S.*)$")
_APPENDIX = re.compile(r"^ {0,5}Appendix\s+([A-Z][a-z]?)[.:]?\s\s*(\S.*)$")
_APPS = re.compile(r"^ {0,7}([A-Z])\.\d+(?:\.\d+)*\.?\s+(\S.*)$")
_UNNUMBERED = {
    "Status of This Memo", "Abstract", "Table of Contents",
    "Copyright Notice", "Authors' Addresses", "Author Addresses",
    "Acknowledgments", "Acknowledgement", "Full Copyright Statement",
    "Security Considerations", "IANA Considerations", "References",
    "Contributors", "Editor's Address", "Editor(s) Address",
}
_TOC_LEADER = re.compile(r"\.{2,}\s*\d+\s*$")
# Old-format ToC entry WITHOUT dot leaders: "4.1.  Format            25" —
# a number-shaped line ending in a wide-spaced page number.
_TOC_PLAIN = re.compile(r"^ {0,10}\d{1,3}(\.\d{1,3}){0,3}\.?[ \t]+\S.*"
                        r"[ \t]{3,}\d{1,4}[ \t]*$")
_JUNK = (
    re.compile(r"^\s*\[Page \d+\]\s*$"),           # page break marker
    re.compile(r"\[Page \d+\]\s*$"),               # running footer
    re.compile(r"^\s{0,3}(Request for Comments: \d+|Internet-Draft .+ "
               r"\(expires .+\))\s*$"),
    re.compile(r"\.{2,}\s*\d+\s*$"),               # dot-leader ToC line
    re.compile(r"(\s\.){4,}\s*\d*\s*$"),           # spaced-leader ToC line
    re.compile(r"^[\s.\u00b7\u2026]{4,}\d*\s*$"),  # pure leader line
    _TOC_PLAIN,                                    # plain-leader ToC line
)
_PAGE_FURNITURE = re.compile(r"\f")
MAX_CHARS = 10000
PART_CHARS = 2400
HARD_CHARS = 4800  # forced cut inside blank-line-free runs (tables)


@dataclass
class Section:
    sec_num: str
    sec_title: str
    start_line: int      # 1-based, inclusive (original file)
    end_line: int        # 1-based, inclusive
    text: str


def _looks_like_title(title: str) -> bool:
    if not title or title.endswith(",") or len(title) > 90:
        return False
    return bool(re.search(r"[A-Za-z]", title))


def _clean_title(raw: str) -> str | None:
    """Extract a real section title from the heading line's tail.

    Real RFC section titles: a short Title Case noun phrase (no commas,
    <=12 words, start uppercase/digit). Two-or-more spaces after the first
    token means an inline definition ("1. MUST   This word ...") -> keep
    the term only. Wrapped prose caught by the number prefix is rejected.
    """
    t = re.split(r"\s{2,}", raw.strip())[0].strip()
    if not t or t.endswith(","):
        return None
    if t.endswith(".") and " " not in t:
        return None  # "(SMTP)." wrapped-reference fragment, never a title
    if re.fullmatch(r"[\d.,\s]+", t):
        return None  # digit/figure runs ("0 1 2", hex offsets), never titles
    if not re.match(r"[A-Z0-9\"'(]", t):
        return None
    if re.search(r"\.\d{1,3}$", t):
        return None  # ToC page-number bleed: "...Dates.89"
    words = t.split()
    if len(words) > 1 and t.endswith("."):
        return None  # prose caught by a renumbered list item, not a title
    if len(words) > 12 or ("," in t and len(words) > 6):
        return None
    if len(words) > 2 and not re.search(r"[a-z]", t):
        return None  # all-caps token runs: figures/hex dumps, not titles
    return t


def find_headings(lines: list[str]) -> list[tuple[int, str, str]]:
    """Return (line_idx, sec_num, sec_title) for body section headings.

    Two-pass: collect raw candidates, then keep only those followed by real
    body text before the next candidate. That drops ToC entries (new-format
    txt has no dot leaders) and consecutive inline-list items in one rule.
    """
    raw: list[tuple[int, str, str]] = []
    for i, ln in enumerate(lines):
        if _TOC_LEADER.search(ln) or _TOC_PLAIN.match(ln):
            continue
        m = _HEADING.match(ln)
        if m:
            title = _clean_title(m.group(2))
            if title:
                raw.append((i, m.group(1), title))
            continue
        m = _APPENDIX.match(ln)
        if m:
            title = _clean_title(m.group(2) or "Appendix")
            if title:
                raw.append((i, f"Appendix {m.group(1)}", title))
            continue
        m = _APPS.match(ln)
        if m:
            title = _clean_title(m.group(2))
            if title:
                raw.append((i, m.group(1), title))
            continue
        stripped = ln.strip().rstrip(".")
        if stripped in _UNNUMBERED and len(ln) - len(ln.lstrip(" ")) <= 5 \
                and ln.strip():
            raw.append((i, "", stripped))

    kept: list[tuple[int, str, str]] = []
    last_major = -1
    for k, (i, num, title) in enumerate(raw):
        if num == "" and title == "Table of Contents":
            kept.append((i, num, title))  # forced boundary; body dropped
            continue
        nxt = raw[k + 1][0] if k + 1 < len(raw) else len(lines)
        if not _clean(lines[i + 1:nxt]).strip():
            continue  # ToC remnant / empty list item: no body before next
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){0,3}", num):
            major = int(num.split(".")[0])
            if major < last_major:
                continue  # renumbered inline list under a later section
            last_major = max(last_major, major)
        elif num.startswith("Appendix"):
            last_major = max(last_major, 10**6)
        elif len(num) == 1 and num.isupper():
            if last_major < 10**6:
                continue  # 'A.1'-style before any Appendix heading: noise
        kept.append((i, num, title))
    return kept


# Boilerplate that appears ONLY in the header/footer zone of a page. Stripped
# for reading (see strip_page_furniture), never for indexing.
_PAGE_EDGE = (
    re.compile(r"^\s*\[?Page \d+\]?\s*$"),
    re.compile(r"\[Page \d+\]\s*$"),               # running footer w/ title
    re.compile(r"^\s*(Request for Comments: \d+|Category: .+|ISSN: \S+|"
               r"Network Working Group|Internet Engineering Task Force|"
               r"Internet Research Task Force|Internet-Draft .+ \(expires .+\)"
               r"|BCP \d+ .+ \[[A-Z ]+\])\s*$"),
)


def strip_page_furniture(text: str) -> str:
    """Return `text` with RFC page furniture removed: form feeds, running
    headers/footers and `[Page N]` markers, with blank runs collapsed to one.

    Only lines in the first/last 4 lines of a page qualify (canonical RFC
    .txt delimits pages with form feeds), so a body line that happens to
    look like a header is never removed. Everything else stays byte-identical
    to the source, which keeps quote hashes stable across releases.

    Differs from _clean(), which drops EVERY blank line for index chunks:
    this keeps paragraph structure because a human/agent is reading it.
    """
    out: list[str] = []
    blanks = 0
    for page in text.split("\f"):
        lines = [ln.rstrip() for ln in page.splitlines()]
        n = len(lines)
        for i, ln in enumerate(lines):
            if not ln.strip():
                blanks += 1
                continue
            if (i <= 4 or i >= n - 4) and any(p.match(ln) for p in _PAGE_EDGE):
                continue
            if out and blanks:
                out.append("")
            blanks = 0
            out.append(ln)
    return "\n".join(out)


def _clean(lines: list[str]) -> str:
    out = []
    for ln in lines:
        ln = _PAGE_FURNITURE.sub("", ln)
        if not ln.strip():
            continue
        if any(p.match(ln) for p in _JUNK):
            continue
        out.append(ln.rstrip())
    return "\n".join(out)


def _split_range(lines: list[str], i0: int, i1: int, num: str,
                 title: str) -> list[Section]:
    """Cut a raw line range [i0, i1) into <=PART_CHARS chunks.

    Cuts at blank-line (paragraph) boundaries; tables/code runs without
    blank lines are cut hard at any line once HARD_CHARS is exceeded.
    Each part carries its OWN original line range.
    """
    whole = _clean(lines[i0:i1])
    if len(whole) <= MAX_CHARS:
        return [Section(num, title, i0 + 1, i1, whole)]
    parts: list[Section] = []
    start, acc = i0, 0
    for i in range(i0, i1):
        ln = _PAGE_FURNITURE.sub("", lines[i])
        keep = bool(ln.strip()) and not any(p.match(ln) for p in _JUNK)
        if keep:
            acc += len(ln) + 1
        over = acc > PART_CHARS and (not ln.strip() or acc > HARD_CHARS)
        if over and i - start > 1:
            body = _clean(lines[start:i])
            if body.strip():
                parts.append(Section(num, title, start + 1, i, body))
            start, acc = i, 0
    body = _clean(lines[start:i1])
    if body.strip():
        parts.append(Section(num, title, start + 1, i1, body))
    n = len(parts)
    if n > 1:  # disambiguate + keep section context in every part
        head = f"{(num + ' ') if num else ''}{title}\n"
        parts = [Section(p.sec_num, f"{title or num} (part {k + 1}/{n})",
                         p.start_line, p.end_line,
                         p.text if k == 0 else head + p.text)
                 for k, p in enumerate(parts)]
    return parts


def split_sections(text: str) -> list[Section]:
    lines = text.lstrip("\ufeff").splitlines()
    heads = find_headings(lines)
    if not heads:
        body = _clean(lines)
        return [Section("", "Entire document", 1, len(lines), body)] \
            if body.strip() else []
    secs: list[Section] = []
    if heads[0][0] > 0:
        secs.extend(_split_range(lines, 0, heads[0][0], "",
                                 "Front matter & boilerplate"))
    for k, (idx, num, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        if title == "Table of Contents" or num == "Table of Contents":
            continue
        body = _clean(lines[idx:end])
        # Heading-only section == ToC remnant (new-format txt has no dot
        # leaders) or inline-list artifact: real sections always have body.
        if not body.strip() or len(body.strip().split("\n")) <= 1:
            continue
        secs.extend(_split_range(lines, idx, end, num, title or num))
    return secs


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()