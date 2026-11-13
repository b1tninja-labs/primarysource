"""Section/paragraph segmentation for RFCs that exist only as .txt.

The legacy chunker (chunker.py) guesses headings line by line and keeps a
"section numbers only go up" rule, so one false heading early on (a status
code like '400 (Bad Request)' at column 0) silently discards every real
section after it: RFC 7230 came out with 2 of 85 headings. This module
segments the document the way RFCXML documents are segmented instead:

1. The document's own Table of Contents is the answer key. Most RFCs have
   one; its entries (number + title) say exactly which headings to find.
2. Headings are located in order after the ToC, as short lines at the left
   margin whose tokens start with the entry's number and title words.
   Numbered entries are anchored first; unnumbered ones (Security
   Considerations, Authors' Addresses) are then searched only between their
   anchored neighbours, so a stray word can't capture them.
3. Headings deeper than the ToC lists (ToCs often stop at depth 2) are
   accepted between anchors only when they are a structural successor of
   the previous heading (first child or next sibling).
4. Without a ToC, a left-margin scan accepts a candidate only when it is a
   plausible successor of the last accepted heading, so a false '400' is
   skipped instead of poisoning the rest of the document.

Every section is then split into paragraph blocks (blank-line separated,
re-joined across page breaks), classified as text / artwork / ABNF, and
the result is returned in rfcxml's ParsedXml shape: the `blocks` table,
paragraph refs (RFC791§3.1¶4), view=code/normative, grep labels and
chunking all work unchanged. Published RFC text never changes, so the
synthetic paragraph numbers are as stable as the RFC Editor's pn ids.

Quality is recorded per document (ToC entries matched, method), so weak
segmentations are visible instead of silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .chunker import _UNNUMBERED, _clean_title
from .rfcxml import _FURNITURE, Block, ParsedXml, XRef, XSection, _toks

VERSION = "2"

_NUM = r"\d{1,3}(?:\.\d{1,3}){0,5}"
_APPX = r"(?:Appendix|APPENDIX|Annex)\s+[A-Z](?:\.\d{1,3})*"
_LETTER = r"[A-Z](?:\.\d{1,3})+|[A-Z](?=\.)"
_LABEL = rf"(?P<lab>{_APPX}|{_LETTER}|{_NUM})"
_LEADER = r"(?:\s*\.(?:\s?\.)+\s*|\s{2,}|\s(?=\d+\s*$))"
_PAGE = r"(?P<page>\d{1,3}|[ivxlc]{1,7})"     # 4 digits is a year
_TOC_NUM = re.compile(rf"^\s*{_LABEL}\.?[:]?\s+(?P<title>\S.*?)"
                      rf"(?:{_LEADER}{_PAGE})?\s*$")
_TOC_UNNUM = re.compile(rf"^\s*(?P<title>[A-Z][A-Za-z'’()/,&\- ]{{2,70}}?)"
                        rf"{_LEADER}{_PAGE}\s*$")
_TOC_HEAD = re.compile(r"^\s*(table\s+of\s+contents|contents)\s*:?\s*$", re.I)
_HEAD = re.compile(rf"^(?P<ind> {{0,4}}){_LABEL}\.?[:]?\s+(?P<title>\S.*)$")
_ABNF = re.compile(r"^\s*[A-Za-z][\w\-]*\s*=/?\s*\S")
_ART = re.compile(r"[+|]-{2,}|-{2,}[+|]|^\s*\|.*\|\s*$|\s{6,}\S.*\s{6,}\S")
_REF_LABEL = re.compile(r"^\s*\[([^\]]{1,40})\]")
_SERIES = re.compile(r"\b(RFC|BCP|STD|FYI)[\s\-]?(\d{1,5})\b")
_NORM = re.compile(r"\b(MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|"
                   r"NOT RECOMMENDED|RECOMMENDED|MAY|REQUIRED|OPTIONAL)\b")
_SEC_OF = re.compile(
    r"[Ss]ections?\s+(?P<sec>\d{1,3}(?:\.\d{1,3})*|[A-Z](?:\.\d{1,3})+)"
    r"\s+of\s+(?:\[(?P<lab>[^\]]{1,40})\]|(?P<ser>RFC|BCP|STD)\s*(?P<n>\d+))")
_LAB_SEC = re.compile(
    r"\[(?P<lab>[^\]]{1,40})\],?\s+[Ss]ection\s+"
    r"(?P<sec>\d{1,3}(?:\.\d{1,3})*|[A-Z](?:\.\d{1,3})+)")
_LAB = re.compile(r"\[(?P<lab>[^\]]{1,40})\]")
_SENT_END = re.compile(r"[.:;!?)\]>\"]\s*$")


@dataclass
class TocEntry:
    sec_num: str          # canonical, chunks vocabulary
    title: str
    line: int             # 1-based ToC line


@dataclass
class Quality:
    method: str           # toc | scan
    toc_entries: int = 0
    matched: int = 0      # ToC entries located in the body
    extra: int = 0        # headings found that the ToC did not list
    headings: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        if self.method == "toc" and self.toc_entries:
            return round(self.matched / self.toc_entries, 3)
        return None


# --------------------------------------------------------------------------
# labels

def canon(label: str) -> str:
    """ToC/heading label -> chunks sec_num: '3.3.3', 'Appendix A', 'A.1'."""
    lab = label.strip().rstrip(".:")
    m = re.fullmatch(r"(?:Appendix|APPENDIX|Annex)\s+([A-Z])((?:\.\d+)*)", lab)
    if m:
        return f"Appendix {m.group(1)}" if not m.group(2) else \
            m.group(1) + m.group(2)
    if re.fullmatch(r"[A-Z]", lab):
        return f"Appendix {lab}"
    return lab


def _depth(sec: str) -> int:
    if sec.startswith("Appendix"):
        return 1
    return sec.count(".") + 1 if sec else 1


def _pn(sec: str, title: str, used: set[str]) -> str:
    if sec.startswith("Appendix"):
        base = "section-appendix." + sec.split()[1].lower()
    elif sec and sec[0].isalpha():
        base = "section-" + sec.lower()
    elif sec:
        base = "section-" + sec
    else:
        base = "section-u." + ("-".join(_toks(title)[:4]) or "x")
    pn, k = base, 2
    while pn in used:
        pn, k = f"{base}.{k}", k + 1
    used.add(pn)
    return pn


def _furniture(ln: str) -> bool:
    return any(p.search(ln) for p in _FURNITURE)


# --------------------------------------------------------------------------
# table of contents

def parse_toc(lines: list[str]) -> tuple[list[TocEntry], int, int]:
    """(entries, first line, last line) of the ToC, or ([], 0, 0)."""
    limit = min(len(lines), max(400, len(lines) // 5))
    start = next((i for i in range(limit) if _TOC_HEAD.match(lines[i])), -1)
    if start < 0:
        return [], 0, 0
    entries: list[TocEntry] = []
    misses, last = 0, start
    for i in range(start + 1, len(lines)):
        ln = lines[i].replace("\f", "")
        if not ln.strip() or _furniture(ln):
            continue
        m = _TOC_NUM.match(ln)
        if m and m.group("page") is None and entries and \
                not ln.startswith(" "):
            break   # page-less ToCs are indented; a margin heading = body
        if m:
            title = re.sub(r"[\s.]+$", "", m.group("title")).strip()
            entries.append(TocEntry(canon(m.group("lab")), title, i + 1))
            misses, last = 0, i
            continue
        wrapped = entries and _indent(ln) > _indent(lines[entries[-1].line - 1])
        m = _TOC_UNNUM.match(ln)
        if m and not wrapped:
            entries.append(TocEntry("", m.group("title").strip(), i + 1))
            misses, last = 0, i
            continue
        if wrapped and re.search(rf"{_LEADER}{_PAGE}\s*$", ln):
            # second line of a wrapped title: "...Interaction with" /
            # "      Proxies ........ 12"
            entries[-1].title += " " + re.sub(rf"{_LEADER}{_PAGE}\s*$", "",
                                              ln).strip()
            misses, last = 0, i
            continue
        misses += 1
        if misses >= 3:
            break
    return entries, start + 1, last + 1


# --------------------------------------------------------------------------
# headings

def _heading_tokens(sec: str, title: str) -> list[tuple[list[str],
                                                         list[str]]]:
    """(label tokens, full title tokens) a body heading may start with."""
    tt = _toks(title)
    if sec.startswith("Appendix"):
        letter = sec.split()[1].lower()
        return [(["appendix", letter], tt), ([letter], tt)]
    if sec[:1].isalpha():              # 'F.1' may be written 'Appendix F.1.'
        return [(_toks(sec), tt), (["appendix"] + _toks(sec), tt)]
    return [(_toks(sec), tt)]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _margin(line: str) -> bool:
    """At the left margin, or centered (RFC 791-era top-level headings);
    body prose sits at a 3-space indent and never qualifies."""
    ind = _indent(line)
    return ind <= 1 or (ind >= 10 and len(line.strip()) <= 60
                        and abs((80 - len(line.rstrip())) - ind) <= 12)


def _matches(line: str, wants, numbered: bool) -> bool:
    """Left-margin line that starts with the label and the title's first
    words (case/punctuation-insensitive; a wrapped title may stop early)."""
    if not line.strip():
        return False
    if re.search(r"(\.\s?){4,}\s*\d+\s*$", line):      # ToC leader line
        return False
    deep = _indent(line) > 4 and not _margin(line)
    lt = _toks(line)
    for lab, tt in wants:
        if not lab:     # unnumbered: whole title, at the margin
            if tt and lt[:len(tt)] == tt and len(lt) <= len(tt) + 2 and \
                    _margin(line):
                return True
            continue
        if lt[:len(lab)] != lab:
            continue
        rest = lt[len(lab):]
        if deep:        # indented by level (RFC 1122): the exact heading only
            if tt and rest == tt and _indent(line) <= 16:
                return True
            continue
        tt = tt[:4]
        n = min(len(rest), len(tt))
        if not tt:
            return bool(numbered and lab)
        if n and rest[:n] == tt[:n] and (n >= min(2, len(tt))
                                         or n == len(rest)):
            if numbered or len(lt) <= len(lab) + len(tt) + 6:
                return True
    return False


def _successor(prev: str, cand: str) -> bool:
    """cand can follow prev in an outline: a first child, the next sibling
    of prev or of an ancestor (small gaps tolerated), or the first
    appendix."""
    if not prev:
        return bool(re.fullmatch(r"[12](?:\.1)?", cand))
    if cand.startswith("Appendix") or (cand[:1].isalpha()):
        return True
    if prev.startswith("Appendix") or prev[:1].isalpha():
        return False
    p = [int(x) for x in prev.split(".")]
    c = [int(x) for x in cand.split(".")]
    if len(c) == len(p) + 1 and c[:-1] == p and 1 <= c[-1] <= 2:
        return True
    for k in range(1, len(p) + 1):          # next sibling at level k
        if len(c) in (k, k + 1) and c[:k - 1] == p[:k - 1] and \
                p[k - 1] < c[k - 1] <= p[k - 1] + 3:
            return len(c) == k or c[k] == 1
    return False


def _followed_by_body(lines: list[str], i: int, label: str = "") -> bool:
    """True when the heading at ``i`` is followed by body text, or directly by its own first child.

    A heading followed straight by its child ("3.5.1" then "3.5.1.1") used to read as a run of numbers, so it
    was rejected and, with it, every descendant, since none of them was a successor any more
    (docs/validation.md, rfc: 41 such headings and 194 descendants, e.g. rfc9288 line 338)."""
    for j in range(i + 1, min(len(lines), i + 12)):
        s = lines[j].strip()
        if not s or _furniture(lines[j]):
            continue
        m = _HEAD.match(lines[j])
        if m and label and canon(m.group("lab")).startswith(label + "."):
            return True
        return not m or lines[j].startswith(" ")
    return False


def _scan_candidates(lines: list[str], lo: int, hi: int,
                     indent: int = 0) -> list[tuple[int, str, str]]:
    out = []
    for i in range(lo, min(hi, len(lines))):
        ln = lines[i]
        m = _HEAD.match(ln)
        if not m or len(m.group("ind")) > indent:
            continue
        if re.search(r"(\.\s?){4,}\s*\d+\s*$", ln):
            continue
        title = _clean_title(m.group("title"))
        if not title:
            continue
        out.append((i + 1, canon(m.group("lab")), title))
    return out


def find_headings(lines: list[str]) -> tuple[list[tuple[int, str, str]],
                                              Quality, tuple[int, int]]:
    """[(line, sec_num, title)] in document order, quality, ToC span."""
    toc, t0, t1 = parse_toc(lines)
    heads: list[tuple[int, str, str]] = []
    numbered = [e for e in toc if e.sec_num]
    q = Quality("toc" if len(numbered) >= 3 else "scan",
                toc_entries=len(toc) if len(numbered) >= 3 else 0)
    body0 = t1 if t1 else 0

    if q.method == "toc":
        at = body0
        anchor: dict[int, int] = {}            # toc index -> line
        for k, e in enumerate(toc):
            if not e.sec_num:
                continue
            wants = _heading_tokens(e.sec_num, e.title)
            for i in range(at, len(lines)):
                if _matches(lines[i], wants, True):
                    anchor[k] = i + 1
                    at = i + 1
                    break
        for k, e in enumerate(toc):             # unnumbered, between anchors
            if e.sec_num:
                continue
            lo = max([anchor[j] for j in anchor if j < k], default=body0)
            hi = min([anchor[j] for j in anchor if j > k],
                     default=len(lines) + 1)
            wants = [([], _toks(e.title))]
            for i in range(lo, hi - 1):
                if _matches(lines[i], wants, False):
                    anchor[k] = i + 1
                    break
        q.matched = len(anchor)
        heads = sorted((anchor[k], toc[k].sec_num, toc[k].title)
                       for k in anchor)
        # deeper headings the ToC omitted: structural successors only
        extra = []
        bounds = [h[0] for h in heads] + [len(lines) + 1]
        for idx, (ln, sec, _t) in enumerate(heads):
            if not sec or sec.startswith("Appendix"):
                continue
            prev = sec
            for cl, cs, ct in _scan_candidates(lines, ln, bounds[idx + 1] - 1):
                if cs.startswith(sec + ".") and _successor(prev, cs) and \
                        _followed_by_body(lines, cl - 1, cs):
                    extra.append((cl, cs, ct))
                    prev = cs
        q.extra = len(extra)
        heads = sorted(heads + extra)
    else:
        prev = ""
        for cl, cs, ct in _scan_candidates(lines, body0, len(lines)):
            if _successor(prev, cs) and _followed_by_body(lines, cl - 1, cs):
                heads.append((cl, cs, ct))
                prev = cs
        q.notes.append("no usable ToC; left-margin successor scan")

    # unnumbered boilerplate / back matter at the left margin: before the
    # ToC (Abstract, Status of This Memo) and after the last numbered one
    known = {u.lower() for u in _UNNUMBERED} | {
        "status of this memo", "acknowledgements", "authors' addresses",
        "author's address", "intellectual property", "full copyright statement",
        "index"}
    have = {h[0] for h in heads}
    last_num = max((h[0] for h in heads if h[1]), default=body0)
    for i, ln in enumerate(lines):
        if i + 1 in have or not ln or ln[0] == " ":
            continue
        s = ln.strip().rstrip(".:")
        if s.lower() not in known or s.lower() == "table of contents":
            continue
        if (t0 and i + 1 < t0) or i + 1 > last_num:
            heads.append((i + 1, "", s))
    heads.sort()
    q.headings = len(heads)
    return heads, q, (t0, t1)


# --------------------------------------------------------------------------
# paragraphs

def _kind(chunk: list[str]) -> tuple[str, str]:
    body = [ln for ln in chunk if ln.strip()]
    if not body:
        return "t", ""
    abnf = sum(1 for ln in body if _ABNF.match(ln))
    if abnf and abnf >= max(1, len(body) // 3) and any(
            re.search(r"=\s*\S.*(/|\*|%x|\"|\()", ln)
            or re.match(r"\s*;", ln) for ln in body):
        return "sourcecode", "abnf"
    art = sum(1 for ln in body if _ART.search(ln))
    alpha = sum(sum(ch.isalpha() for ch in ln) for ln in body)
    chars = sum(len(ln.strip()) for ln in body) or 1
    if (len(body) >= 2 and art >= max(1, len(body) // 3)) or \
            (len(body) >= 3 and alpha / chars < 0.45):
        return "artwork", ""
    return "t", ""


def paragraphs(lines: list[str], a: int, b: int) -> list[tuple[int, int]]:
    """(start, end) line spans of blank-separated paragraphs in [a, b];
    a paragraph broken by a page break (furniture + blanks, previous line
    not ending a sentence) is re-joined."""
    spans: list[list[int]] = []
    cur: list[int] | None = None
    gap_furn = False
    for n in range(a, b + 1):
        ln = lines[n - 1].replace("\f", "")
        if _furniture(ln) or lines[n - 1].startswith("\f"):
            gap_furn = True
            if cur:
                spans.append(cur)
                cur = None
            continue
        if not ln.strip():
            if cur:
                spans.append(cur)
                cur = None
            continue
        if cur is None:
            if gap_furn and spans and not _SENT_END.search(
                    lines[spans[-1][1] - 1]) and ln.startswith(" "):
                cur = spans.pop()       # continue the paragraph split by a page
            else:
                cur = [n, n]
            gap_furn = False
        cur[1] = n
    if cur:
        spans.append(cur)
    return [(s, e) for s, e in spans]


def _text(lines: list[str], s: int, e: int, kind: str) -> str:
    rows = [lines[n - 1].replace("\f", "").rstrip() for n in range(s, e + 1)
            if not _furniture(lines[n - 1])]
    rows = [r for r in rows if r.strip()]
    if kind in ("artwork", "sourcecode"):
        ind = min((len(r) - len(r.lstrip()) for r in rows), default=0)
        return "\n".join(r[ind:] for r in rows)
    return re.sub(r"\s+", " ", " ".join(r.strip() for r in rows)).strip()


# --------------------------------------------------------------------------
# document

def segment(txt: str, doc_id: str) -> tuple[ParsedXml, Quality]:
    lines = txt.lstrip("﻿").splitlines()
    heads, q, (t0, t1) = find_headings(lines)
    if not heads:   # early RFCs without any structure: one body section
        heads = [(1, "", "Entire document")]
        q.notes.append("no headings found; single body section")
    used: set[str] = set()
    sections: list[XSection] = []
    for k, (ln, sec, title) in enumerate(heads):
        nxt = heads[k + 1][0] if k + 1 < len(heads) else len(lines) + 1
        end = nxt - 1
        if t0 and ln < t0 <= end:          # the ToC belongs to no section
            end = t0 - 2
        # a heading may wrap onto the next line (indented continuation)
        body0 = ln + 1
        if body0 <= end and lines[body0 - 1].startswith("    ") and \
                not lines[body0 - 1].strip().endswith(".") and \
                len(lines[body0 - 1].strip()) < 60 and \
                lines[ln - 1].rstrip()[-1:].isalpha() and \
                body0 + 1 <= end and not lines[body0].strip():
            title = f"{title} {lines[body0 - 1].strip()}"
            body0 += 1
        x = XSection(_pn(sec, title, used), "", sec, title, _depth(sec),
                     head_line=ln, end_line=max(ln, end))
        for s, e in paragraphs(lines, body0, x.end_line):
            kind, lang = _kind([lines[n - 1] for n in range(s, e + 1)])
            text = _text(lines, s, e, kind)
            if not text:
                continue
            x.blocks.append(Block(f"{x.pn}-{len(x.blocks) + 1}", kind, text,
                                  sorted(set(_NORM.findall(text)),
                                         key=text.find)
                                  if kind == "t" else [], lang, s, e,
                                  exact=True))
        sections.append(x)
    px = ParsedXml(doc_id, sections, [], {})
    px.xrefs = _xrefs(px)
    return px, q


def _xrefs(px: ParsedXml) -> list[XRef]:
    """Citations with their source section, from reference lists + body
    phrases ('Section 4.2 of [RFC1234]', '[X], Section 3', '[X]')."""
    refs: dict[str, tuple[str, bool]] = {}
    for sec in px.sections:
        if "reference" not in sec.title.lower():
            continue
        norm = "normative" in sec.title.lower()
        for b in sec.blocks:
            m = _REF_LABEL.match(b.text)
            if not m:
                continue
            lab = m.group(1).strip()
            s = _SERIES.search(lab.replace(" ", "")) or _SERIES.search(b.text)
            if s:
                refs[lab] = (f"{s.group(1)}{int(s.group(2))}", norm)
                b.kind = "reference"
    out: list[XRef] = []
    for sec in px.sections:
        if "reference" in sec.title.lower():
            continue
        for b in sec.blocks:
            if b.kind != "t":
                continue
            seen = set()
            for m in _SEC_OF.finditer(b.text):
                dst = (refs.get(m.group("lab"), ("", False))[0]
                       if m.group("lab") else
                       f"{m.group('ser')}{int(m.group('n'))}")
                if dst:
                    seen.add((dst, m.group("sec")))
            for m in _LAB_SEC.finditer(b.text):
                dst = refs.get(m.group("lab"), ("", False))[0]
                if dst:
                    seen.add((dst, m.group("sec")))
            for m in _LAB.finditer(b.text):
                dst = refs.get(m.group("lab"), ("", False))[0]
                if dst and not any(d == dst for d, _s in seen):
                    seen.add((dst, ""))
            for dst, ds in seen:
                lab = next((k for k, v in refs.items() if v[0] == dst), dst)
                out.append(XRef(b.pn, sec.sec_num, dst, ds, lab,
                                refs.get(lab, ("", False))[1]))
    px.refs = refs
    return out
