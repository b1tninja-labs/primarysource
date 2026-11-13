"""Exact section/paragraph structure from RFCXML v3 (RFC 8650 and later).

The txt chunker (chunker.py) has to guess headings from layout. For every RFC
published since RFC 8650 the RFC Editor also publishes the canonical RFCXML
source, already "prepped" (RFC 7998): every section and every block carries a
`pn` id such as 'section-9.6' or 'section-9.6-3', the same ids the official
HTML uses as anchors. So for those documents we take structure from XML and
keep the txt only as the coordinate system: each block is aligned back onto
the txt lines it rendered to, which keeps get_rfc / read / cite line ranges
identical in meaning for XML and txt-only documents.

What the XML adds beyond boundaries:
  * paragraph-level ids (pn) -> citations finer than a section;
  * <bcp14> markup -> which blocks state MUST/SHOULD requirements;
  * typed <sourcecode type="abnf|yang|asn.1|..."> and <artwork>;
  * <xref target=REF section="7.7"> -> section-precise cross-RFC edges.

Alignment works on lowercase alphanumeric tokens, so line wrapping,
indentation, hyphen breaks and bracket rendering do not matter; blocks are
anchored with 5-gram lookups and walked strictly in document order.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .chunker import HARD_CHARS, MAX_CHARS, PART_CHARS, Section, _clean

# Bump when parsing/rendering/alignment changes: build_chunks folds it into
# the per-doc source hash so every XML document is re-chunked.
PARSER_VERSION = "3"

_TOK = re.compile(r"[a-z0-9]+")
_NGRAM = 5
_MAX_TRAIL = 12
_BACKTRACK = 40
# Running header/footer of xml2rfc txt pages; skipped for alignment only.
_FURNITURE = (
    re.compile(r"^\f?RFC \d+ {2,}.*\S {2,}\S+ \d{4}\s*$"),
    re.compile(r"\[Page \d+\]\s*$"),
)
_BLOCK_TAGS = {"t", "ul", "ol", "dl", "figure", "artwork", "sourcecode",
               "table", "aside", "blockquote", "artset"}
_DOC_URL = re.compile(r"/info/(rfc|bcp|std|fyi)(\d+)\b", re.I)


@dataclass
class Block:
    pn: str
    kind: str              # t|ul|ol|dl|figure|artwork|sourcecode|table|...
    text: str
    bcp14: list[str]
    lang: str = ""         # sourcecode/artwork type, e.g. 'abnf'
    start_line: int = 0    # 1-based txt line range, 0 = not aligned
    end_line: int = 0
    exact: bool = False    # False: range interpolated from neighbours


@dataclass
class XSection:
    pn: str
    anchor: str
    sec_num: str           # same vocabulary as chunks.sec_num
    title: str
    depth: int
    blocks: list[Block] = field(default_factory=list)
    head_line: int = 0     # txt line of the heading
    end_line: int = 0      # last txt line of this section's OWN text


@dataclass
class XRef:
    src_pn: str            # block the citation sits in
    src_sec: str
    dst_doc: str           # 'RFC9002'
    dst_sec: str           # '7.7' or '' for whole-document citations
    ref_anchor: str        # 'QUIC-RECOVERY'
    normative: bool


@dataclass
class ParsedXml:
    doc_id: str
    sections: list[XSection]
    xrefs: list[XRef]
    refs: dict[str, tuple[str, bool]]   # bib anchor -> (doc_id, normative)


# --------------------------------------------------------------------------
# rendering

def _ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def sec_num_of(pn: str, numbered: bool) -> str:
    """'section-9.6' -> '9.6', 'section-appendix.a' -> 'Appendix A',
    'section-a.1' -> 'A.1'; unnumbered sections -> '' (as the txt chunker)."""
    if not numbered:
        return ""
    s = pn[len("section-"):] if pn.startswith("section-") else pn
    if s.startswith("appendix."):
        rest = s.split(".", 1)[1]
        if "." not in rest:
            return "Appendix " + rest.upper()
        s = rest                     # 'appendix.b.1' is stored as 'B.1'
    m = re.fullmatch(r"([a-z])((?:\.\d+)+)", s)
    if m:
        return m.group(1).upper() + m.group(2)
    if re.fullmatch(r"\d+(?:\.\d+)*", s):
        return s
    return ""


class _Renderer:
    def __init__(self, refs: dict[str, tuple[str, bool]]):
        self.refs = refs
        self.xrefs: list[tuple[ET.Element, str]] = []   # (xref, bib anchor)

    def inline(self, e: ET.Element) -> str:
        parts = [e.text or ""]
        for c in e:
            parts.append(self._inline_el(c))
            parts.append(c.tail or "")
        return "".join(parts)

    def _inline_el(self, c: ET.Element) -> str:
        tag = c.tag
        if tag in ("iref", "cref"):
            return ""
        if tag == "br":
            return " "
        if tag in ("sup", "sub"):    # txt renders XMSS<sup>MT</sup> as XMSS^MT
            return ("^" if tag == "sup" else "_") + self.inline(c)
        if tag == "contact":         # <contact fullname="..."/> is empty
            return c.get("fullname") or c.get("asciiFullname") or \
                self.inline(c)
        if tag == "eref":
            return self.inline(c).strip() or c.get("target", "")
        if tag == "relref":           # v2 leftover, treated like xref
            tag = "xref"
        if tag == "xref":
            inner = _ws(self.inline(c))
            tgt = c.get("target", "")
            dc = c.get("derivedContent", "") or tgt
            if tgt in self.refs or c.get("section"):
                self.xrefs.append((c, tgt))
                label = f"[{dc}]"
                sec = c.get("section")
                if sec:
                    fmt = c.get("sectionFormat", "of")
                    if fmt == "comma":
                        label = f"{label}, Section {sec}"
                    elif fmt == "parens":
                        label = f"{label} (Section {sec})"
                    elif fmt == "bare":
                        label = sec
                    else:
                        label = f"Section {sec} of {label}"
                return f"{inner} {label}" if inner else label
            return inner or dc
        return self.inline(c)

    def block(self, e: ET.Element) -> str:
        tag = e.tag
        if tag == "t":
            return _ws(self.inline(e))
        if tag in ("artwork", "sourcecode"):
            if e.get("type") == "svg":
                return ""
            return (e.text or "").strip("\n").rstrip()
        if tag == "artset":
            arts = e.findall("artwork")
            pick = next((a for a in arts if a.get("type") == "ascii-art"),
                        next((a for a in arts if a.get("type") != "svg"),
                             None))
            return self.block(pick) if pick is not None else ""
        if tag == "figure":
            out = []
            for c in e:
                if c.tag in ("artwork", "sourcecode", "artset"):
                    out.append(self.block(c))
            out.append(_caption(e, "Figure", self))
            return "\n".join(x for x in out if x)
        if tag in ("ul", "ol"):
            out = []
            for k, li in enumerate(e.findall("li"), 1):
                mark = "-" if tag == "ul" else (li.get("derivedCounter")
                                                or f"{k}.")
                out.append(f"{mark} {self.flow(li)}")
            return "\n".join(out)
        if tag == "dl":
            out, term = [], ""
            for c in e:
                if c.tag == "dt":
                    term = _ws(self.inline(c))
                elif c.tag == "dd":
                    out.append(f"{term}: {self.flow(c)}" if term
                               else self.flow(c))
                    term = ""
            return "\n".join(out)
        if tag == "table":
            out = [" | ".join(self.flow(td) for td in tr
                              if td.tag in ("td", "th"))
                   for tr in e.iter("tr")]
            out.append(_caption(e, "Table", self))
            return "\n".join(x for x in out if x)
        if tag in ("aside", "blockquote"):
            return self.flow(e)
        return _ws(self.inline(e))

    def flow(self, e: ET.Element) -> str:
        """Element that may hold either inline text or nested blocks (li,
        dd, td, aside)."""
        kids = [c for c in e if c.tag in _BLOCK_TAGS]
        if not kids:
            return _ws(self.inline(e))
        lead = _ws(e.text or "")
        out = [lead] if lead else []
        for c in kids:
            out.append(self.block(c))
            if _ws(c.tail or ""):
                out.append(_ws(c.tail or ""))
        return "\n".join(x for x in out if x)


def _caption(e: ET.Element, kind: str, r: _Renderer) -> str:
    """'Table 2: Possible Mapping ...' — placed AFTER the body, where the
    txt rendering puts it, so alignment sees tokens in the same order."""
    name = e.find("name")
    m = re.search(r"-(\d+)$", e.get("pn") or "")
    num = f" {m.group(1)}" if m else ""
    if name is None:
        return f"{kind}{num}" if num else ""
    return f"{kind}{num}: {_ws(r.inline(name))}"


def _bcp14(e: ET.Element) -> list[str]:
    seen: list[str] = []
    for b in e.iter("bcp14"):
        w = _ws("".join(b.itertext())).upper()
        if w and w not in seen:
            seen.append(w)
    return seen


def _ref_doc(el: ET.Element) -> str:
    """Cited document id. A reference carrying both 'BCP 145' and 'RFC 8085'
    resolves to the RFC (the text a section number refers to); a
    <referencegroup> for BCP 14 has no single RFC and stays 'BCP14'."""
    found: dict[str, str] = {}
    for si in el.findall("seriesInfo"):
        name = (si.get("name") or "").upper()
        if name in ("RFC", "BCP", "STD", "FYI") and \
                (si.get("value") or "").isdigit():
            found.setdefault(name, f"{name}{int(si.get('value'))}")
    for name in ("RFC", "BCP", "STD", "FYI"):
        if name in found:
            return found[name]
    m = _DOC_URL.search(el.get("target") or "")
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else ""


def _ref_text(el: ET.Element, r: _Renderer) -> str:
    if el.tag == "referencegroup":
        inner = " ".join(_ref_text(x, r).split("] ", 1)[-1]
                         for x in el.findall("reference"))
        return f"[{el.get('anchor')}] {inner}"
    front = el.find("front")
    title = _ws(r.inline(front.find("title"))) if front is not None and \
        front.find("title") is not None else ""
    authors = ", ".join(a.get("fullname") or a.get("surname") or
                        _ws("".join(a.itertext()))
                        for a in (front.findall("author")
                                  if front is not None else []))
    series = ", ".join(f"{s.get('name')} {s.get('value')}"
                       for s in el.findall("seriesInfo")
                       if s.get("name") != "DOI")
    date = front.find("date") if front is not None else None
    when = " ".join(x for x in ((date.get("month") or "",
                                 date.get("year") or "")
                                if date is not None else ()) if x)
    bits = [b for b in (authors, f'"{title}"' if title else "", series, when)
            if b]
    return f"[{el.get('anchor')}] " + ", ".join(bits)


def _author_text(a: ET.Element) -> str:
    """Name, role, organization, email. Postal lines are left out: xml2rfc
    orders them per country convention, which would break alignment, and
    nobody searches an RFC for a street address."""
    bits = [a.get("fullname") or "",
            f"({a.get('role')})" if a.get("role") else ""]
    org = a.find("organization")
    if org is not None:
        bits.append(_ws("".join(org.itertext())))
    head = _ws(" ".join(b for b in bits if b))
    email = a.find("address/email")
    if email is not None and email.text:
        return f"{head}\nEmail: {email.text.strip()}"
    return head


# --------------------------------------------------------------------------
# parsing

def parse(xml_text: str, doc_id: str) -> ParsedXml:
    root = ET.fromstring(xml_text.encode("utf-8"))
    if root.tag != "rfc" or root.get("version") != "3":
        raise ValueError(f"not RFCXML v3 (root={root.tag} "
                         f"version={root.get('version')})")
    refs: dict[str, tuple[str, bool]] = {}
    back = root.find("back")
    if back is not None:
        for grp in back.iter("references"):
            name = grp.find("name")
            normative = name is not None and \
                "normative" in "".join(name.itertext()).lower()
            for el in grp:
                if el.tag in ("reference", "referencegroup") and \
                        el.get("anchor"):
                    refs[el.get("anchor")] = (_ref_doc(el), normative)
    r = _Renderer(refs)
    sections: list[XSection] = []
    xrefs: list[XRef] = []

    def add_blocks(sec: XSection, elems):
        for c in elems:
            if c.tag not in _BLOCK_TAGS and c.tag not in (
                    "reference", "referencegroup", "author"):
                continue
            mark = len(r.xrefs)
            if c.tag in ("reference", "referencegroup"):
                text, kind = _ref_text(c, r), "reference"
            elif c.tag == "author":   # Authors' Addresses is generated
                text, kind = _author_text(c), "author"
            else:
                text, kind = r.block(c), c.tag
            if not text.strip():
                continue
            pn = c.get("pn") or ""
            lang = ""
            if c.tag == "figure":
                inner = next((x for x in c if x.tag in
                              ("artwork", "sourcecode", "artset")), None)
                if inner is not None:
                    pn = pn or inner.get("pn") or ""
                    kind = "sourcecode" if inner.tag == "sourcecode" \
                        else "artwork"
                    lang = inner.get("type") or ""
            elif c.tag in ("artwork", "sourcecode"):
                lang = c.get("type") or ""
            if not pn:
                pn = c.get("anchor") or f"{sec.pn}-x{len(sec.blocks) + 1}"
            sec.blocks.append(Block(pn, kind, text, _bcp14(c), lang))
            for x, anchor in r.xrefs[mark:]:
                dst, norm = refs.get(anchor, ("", False))
                if dst:
                    xrefs.append(XRef(pn, sec.sec_num, dst,
                                      x.get("section") or "", anchor, norm))

    def walk(e: ET.Element, depth: int):
        for c in e:
            if c.tag not in ("section", "references"):
                continue
            pn = c.get("pn") or ""
            if pn.startswith("section-toc"):
                continue
            name = c.find("name")
            title = _ws(r.inline(name)) if name is not None else ""
            numbered = c.get("numbered", "true") != "false" and \
                not pn.startswith("section-boilerplate")
            sec = XSection(pn, c.get("anchor") or "",
                           sec_num_of(pn, numbered), title, depth)
            sections.append(sec)
            add_blocks(sec, list(c))
            walk(c, depth + 1)

    front = root.find("front")
    if front is not None:
        ab = front.find("abstract")
        if ab is not None:
            sec = XSection(ab.get("pn") or "section-abstract", "abstract",
                           "", "Abstract", 1)
            sections.append(sec)
            add_blocks(sec, list(ab))
        bp = front.find("boilerplate")
        if bp is not None:
            walk(bp, 1)
    for part in ("middle", "back"):
        el = root.find(part)
        if el is not None:
            walk(el, 1)
    return ParsedXml(doc_id, sections, xrefs, refs)


# --------------------------------------------------------------------------
# alignment onto txt lines

def _toks(s: str) -> list[str]:
    return _TOK.findall(s.lower())


class _TxtIndex:
    def __init__(self, lines: list[str]):
        self.lines = lines
        self.toks: list[str] = []
        self.line_of: list[int] = []
        for i, ln in enumerate(lines):
            if any(p.search(ln) for p in _FURNITURE):
                continue
            for t in _toks(ln):
                self.toks.append(t)
                self.line_of.append(i + 1)
        self.grams: dict[tuple, list[int]] = {}
        for p in range(len(self.toks) - _NGRAM + 1):
            self.grams.setdefault(tuple(self.toks[p:p + _NGRAM]), []).append(p)

    def _first_at_or_after(self, gram: tuple, lo: int, hi: int) -> int | None:
        for p in self.grams.get(gram, ()):
            if lo <= p < hi:
                return p
        return None

    def tok_at_line(self, line: int) -> int:
        """Index of the first token on or after 1-based `line`."""
        import bisect
        return bisect.bisect_left(self.line_of, line)

    def locate(self, bt: list[str], lo: int,
               hi: int) -> tuple[int, int] | None:
        """Token span [start, end] of block tokens `bt` inside [lo, hi).

        [lo, hi) is the owning section's span between its heading and the
        next heading, so a sentence repeated elsewhere in the document can
        never capture the block. `lo` may sit a little past the true start
        when the previous block's end overshot (table cell wrapping), so
        n-gram search starts _BACKTRACK tokens early."""
        n = len(bt)
        if n == 0 or lo >= hi:
            return None
        if n < _NGRAM:   # 'None.' etc: backtracking would re-find the last one
            for p in range(lo, max(lo, min(hi, len(self.toks)) - n + 1)):
                if self.toks[p:p + n] == bt:
                    return p, p + n - 1
            return None
        lo = max(0, lo - _BACKTRACK)
        # Every gram votes for the start it implies; the densest cluster
        # wins. Taking the first or earliest match instead lets one gram
        # shared with a neighbouring paragraph drag the block (and the
        # cursor) to the wrong place.
        cands = []
        for off in range(0, min(n - _NGRAM + 1, 80)):
            p = self._first_at_or_after(tuple(bt[off:off + _NGRAM]),
                                        lo + off, hi)
            if p is not None:
                cands.append(p - off)
        if not cands:
            return None
        start = max(lo, _densest(cands))
        ends = []
        for off in range(n - _NGRAM, max(-1, n - _NGRAM - 80), -1):
            p = self._first_at_or_after(tuple(bt[off:off + _NGRAM]),
                                        start + off - n // 4 - 50,
                                        min(hi, start + off + n // 4 + 50))
            if p is not None and p >= start:
                ends.append(p + (n - off) - 1)
        end = _densest(ends) if ends else start + n - 1
        end = min(end, start + n + n // 3 + 10, hi - 1, len(self.toks) - 1)
        return start, max(start, end)


def _densest(vals: list[int], slack: int = 4) -> int:
    """Value with the most other values within +-slack (ties: earliest)."""
    best, best_n = vals[0], -1
    for v in sorted(set(vals)):
        c = sum(1 for w in vals if abs(w - v) <= slack)
        if c > best_n:
            best, best_n = v, c
    return best


def _heading_tokens(sec: XSection) -> list[str]:
    return _toks(f"{sec.sec_num} {sec.title}")


def _is_heading(line: str, want: list[str], numbered: bool) -> bool:
    """xml2rfc txt puts section headings at column 0 (ToC entries and body
    text are indented), first line only when the title wraps."""
    if not line or line[0] in " \t\f" or not want:
        return False
    lt = _toks(line)
    if not lt or want[:len(lt)] != lt:
        return False
    if numbered:      # number + at least the first title word
        return len(lt) >= min(len(want), len(_toks(want[0])) + 1)
    return len(lt) == len(want) or len(lt) >= 3


def align(px: ParsedXml, txt: str) -> list[str]:
    """Fill block/section line ranges in place; returns lines of txt.

    Pass 1 finds every section heading in document order. Pass 2 aligns
    each section's blocks only inside its own [heading, next heading) span.
    """
    lines = txt.lstrip("\ufeff").splitlines()
    ix = _TxtIndex(lines)
    secs = px.sections
    at = 0
    for sec in secs:
        want = _heading_tokens(sec)
        for ln in range(at + 1, len(lines) + 1):
            if _is_heading(lines[ln - 1], want, bool(sec.sec_num)):
                sec.head_line, at = ln, ln
                break

    heads = [s.head_line for s in secs]
    for k, sec in enumerate(secs):
        nxt = next((h for h in heads[k + 1:] if h), len(lines) + 1)
        prev = next((h for h in reversed(heads[:k]) if h), 0)
        lo = ix.tok_at_line((sec.head_line or prev) + 1)
        hi = ix.tok_at_line(nxt)
        cursor = lo
        for b in sec.blocks:
            bt = _toks(b.text)
            if b.kind == "author":   # name/org lines precede the postal ones
                bt = _toks(b.text.split("\n", 1)[0])[:4]
            span = ix.locate(bt, cursor, hi)
            if span is None:
                continue
            # _BACKTRACK may reach above the heading; never past it.
            b.start_line = max(ix.line_of[span[0]], sec.head_line + 1)
            b.end_line = max(b.start_line, ix.line_of[span[1]])
            b.exact = True
            cursor = span[1] + 1

    for k, sec in enumerate(secs):
        if not sec.head_line:   # unmatched heading: just before its text
            own = [b for b in sec.blocks if b.exact]
            sec.head_line = max(1, own[0].start_line - 1) if own else (
                secs[k - 1].head_line + 1 if k else 1)
    for k, sec in enumerate(secs):
        nxt = next((s.head_line for s in secs[k + 1:]
                    if s.head_line > sec.head_line), len(lines) + 1)
        # Unaligned blocks share the gap between their aligned neighbours,
        # never leaving the section's own [heading, next heading) span.
        prev_end = sec.head_line
        for i, b in enumerate(sec.blocks):
            if b.exact:
                prev_end = b.end_line
                continue
            after = next((x.start_line for x in sec.blocks[i + 1:]
                          if x.exact), nxt)
            b.start_line = min(prev_end + 1, max(sec.head_line, after - 1))
            b.end_line = max(b.start_line, after - 1)
            prev_end = b.end_line
        end = nxt - 1
        own_last = max((b.end_line for b in sec.blocks), default=0)
        if own_last:
            # A page break between the last block and the next heading is
            # < ~8 lines of furniture; a bigger gap is the ToC (not a
            # section in XML) and must not be billed to Copyright Notice.
            end = min(end, own_last + _MAX_TRAIL)
        sec.end_line = max(sec.head_line, end)
    return lines


# --------------------------------------------------------------------------
# chunks

def _chunk_section(sec: XSection) -> list[Section]:
    # First line mirrors the txt heading, as txt chunks start with it.
    head = f"{sec.sec_num}.  {sec.title}" if sec.sec_num else sec.title
    bodies = [b.text for b in sec.blocks]
    whole = "\n".join([head] + bodies)
    if not bodies:
        return []
    title = sec.title or sec.sec_num
    if len(whole) <= MAX_CHARS:
        return [Section(sec.sec_num, title, sec.head_line, sec.end_line,
                        whole)]
    # Pack blocks into <= PART_CHARS parts; a single oversized block is cut
    # at line boundaries with proportionally interpolated line ranges.
    pieces: list[tuple[str, int, int]] = []
    for b in sec.blocks:
        if len(b.text) <= HARD_CHARS:
            pieces.append((b.text, b.start_line, b.end_line))
            continue
        tl = b.text.split("\n")
        span = max(1, b.end_line - b.start_line + 1)
        acc: list[str] = []
        a0 = 0
        for i, ln in enumerate(tl + [None]):
            if ln is None or (acc and sum(len(x) + 1 for x in acc)
                              + len(ln) > PART_CHARS):
                s = b.start_line + span * a0 // len(tl)
                e = b.start_line + span * i // len(tl) - 1
                pieces.append(("\n".join(acc), s, max(s, e)))
                acc, a0 = [], i
            if ln is not None:
                acc.append(ln)
    parts: list[list[tuple[str, int, int]]] = [[]]
    size = 0
    for p in pieces:
        if parts[-1] and size + len(p[0]) > PART_CHARS:
            parts.append([])
            size = 0
        parts[-1].append(p)
        size += len(p[0]) + 1
    out: list[Section] = []
    n = len(parts)
    for k, grp in enumerate(parts):
        start = sec.head_line if k == 0 else grp[0][1]
        end = (parts[k + 1][0][1] - 1) if k + 1 < n else sec.end_line
        text = "\n".join([head] + [g[0] for g in grp])
        out.append(Section(sec.sec_num, f"{title} (part {k + 1}/{n})"
                           if n > 1 else title, start, max(start, end), text))
    return out


def xml_sections(px: ParsedXml, lines: list[str]) -> list[Section]:
    """Chunker-compatible Sections for an aligned ParsedXml: front matter
    (txt, up to the Abstract), then one chunk per section's own text."""
    out: list[Section] = []
    first = min((s.head_line for s in px.sections if s.head_line),
                default=1)
    if first > 1:
        body = _clean(lines[:first - 1])
        if body.strip():
            out.append(Section("", "Front matter & boilerplate", 1,
                               first - 1, body))
    for sec in px.sections:
        out.extend(_chunk_section(sec))
    return out


def blocks_rows(px: ParsedXml) -> list[tuple]:
    """Rows for the `blocks` table (doc order).

    Each section starts with a kind='heading' row whose pn is the section's
    own id and whose range is the WHOLE section including subsections; it
    exists even when the section has no text of its own (e.g. '1.
    Introduction' holding only 1.1-1.4), which chunks cannot represent."""
    rows, k = [], 0
    secs = px.sections
    for i, sec in enumerate(secs):
        deep_end = next((s.head_line - 1 for s in secs[i + 1:]
                         if s.depth <= sec.depth and s.head_line > sec.head_line),
                        max([sec.end_line] + [s.end_line for s in secs[i + 1:]]))
        k += 1
        rows.append((px.doc_id, sec.pn, k, "heading", sec.sec_num, sec.title,
                     sec.anchor, sec.head_line, max(sec.head_line, deep_end),
                     sec.title, "", "", 1))
        for b in sec.blocks:
            k += 1
            rows.append((px.doc_id, b.pn, k, b.kind, sec.sec_num, sec.title,
                         sec.anchor, b.start_line, b.end_line, b.text,
                         ",".join(b.bcp14), b.lang, int(b.exact)))
    return rows


def xref_rows(px: ParsedXml) -> list[tuple]:
    seen, rows = set(), []
    for x in px.xrefs:
        key = (x.src_pn, x.dst_doc, x.dst_sec)
        if key in seen:
            continue
        seen.add(key)
        rows.append((px.doc_id, x.src_pn, x.src_sec, x.dst_doc, x.dst_sec,
                     x.ref_anchor, int(x.normative)))
    return rows
