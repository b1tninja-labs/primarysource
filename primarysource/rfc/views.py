"""Agent-facing views over the library, addressed by citation refs.

One reference grammar is used everywhere, and every view both accepts and
emits it, so a page footer's "next:" IS the citation of where the next page
starts (resumable, readable, and citable as-is):

    RFC9000                 whole document (header, abstract, outline)
    RFC9000§9.6             a section, subsections included
    RFC9000§9.6¶3           paragraph 3 of §9.6 (RFCXML pn ids for RFC
                            8650+, txtseg paragraphs for older RFCs)
    RFC9000#section-9.6-3   the same paragraph by its RFC Editor id/anchor
    RFC9000#table-2         any RFCXML block id (tables, figures, refs)
    RFC9000:2964-2979       a txt line range (any document)

Accepted spellings: 'rfc 9000', 'BCP14' (aliases follow to the RFC),
'section 9.6' / 's9.6' for §, 'p3' / 'para 3' for ¶.

Pages are cut on block (paragraph) boundaries within a character budget,
never mid-sentence, and text is the RFC Editor's own txt minus page
furniture, so line numbers stay true to the canonical file. Everything
returns plain text: JSON-escaping prose costs tokens for nothing.
"""

from __future__ import annotations

import bisect
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError

from . import cite as _cite
from . import query as q
from .index import search as _s
from .index.rfcxml import _FURNITURE

CHARS_PER_TOKEN = 4
NORM_RE = re.compile(
    r"\b(MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|"
    r"NOT RECOMMENDED|RECOMMENDED|MAY|REQUIRED|OPTIONAL)\b"
)


class RefError(LibError, ValueError):
    """Bad or unresolvable reference, or a library not ready to answer. A
    `LibError`: `hint` names the tool call to make next and `action` the
    command a human runs (PLAN.md §5.10); the MCP server adds the ref forms
    to a ref problem that names neither."""


def _fetch_failed(exc: BaseException) -> bool:
    """A fetch from rfc-editor.org failed: an OSError, or an httpx error.
    httpx is imported only by the code that fetches, so when it is not
    loaded no httpx error can have been raised."""
    if isinstance(exc, OSError):
        return True
    httpx = sys.modules.get("httpx")
    return httpx is not None and isinstance(exc, httpx.HTTPError)


@dataclass
class Ref:
    doc: str  # as asked ('BCP14')
    served: str  # document carrying the text ('RFC2119')
    sec: str = ""  # canonical sec_num
    para: int | None = None
    pn: str = ""  # RFCXML block id
    start: int | None = None
    end: int | None = None

    def is_doc(self) -> bool:
        return not (self.sec or self.pn or self.para or self.start)


_REF = re.compile(
    r"^\s*(?P<doc>(?:rfc|bcp|std|fyi)?[\s\-_]*\d{1,5})\s*"
    r"(?:(?:§|section\s+|sect?\.?\s*|s(?=\d|[A-Z]\b|[A-Z]\.))\s*"
    r"(?P<sec>[^¶:#]+?))?\s*"
    r"(?:(?:¶|para\s*|p)\s*(?P<para>\d+))?\s*"
    r"(?:#(?P<pn>[\w.\-]+))?\s*"
    r"(?::\s*(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?)?\s*$",
    re.I,
)


def _require_library(conn: sqlite3.Connection) -> None:
    from . import library

    if not library.initialized(conn):
        raise RefError(*library.not_initialized(conn))


def _ensure_text(conn: sqlite3.Connection, doc: str) -> None:
    """Fetch + index a document on first use (see rfclib.library)."""
    from . import library
    from .config import NetworkDisabled

    try:
        library.ensure_indexed(conn, doc)
    except NetworkDisabled as e:
        raise RefError(e.message, e.hint, e.action) from None
    except Exception as e:
        if not _fetch_failed(e):
            raise
        raise RefError(
            f"could not fetch {doc} from rfc-editor.org ({e})",
            "retry the same call later",
            "rfclib sync (while online)",
        ) from None


def parse_ref(conn: sqlite3.Connection, raw: str, need_text: bool = True) -> Ref:
    """need_text: fetch and index the document if it is not local yet
    (False for views that only need the catalog, e.g. errata)."""
    m = _REF.match(raw or "")
    if not m:
        raise RefError(f"can't parse ref {raw!r}")
    _require_library(conn)
    try:
        doc = q.normalize_doc_id(m.group("doc"))
        q.get_doc_row(conn, doc)
    except (ValueError, q.NotFound) as e:
        raise RefError(f"unknown document in {raw!r}: {e}") from None
    if need_text:
        _ensure_text(conn, q.resolve(conn, doc))
    sec = _s.norm_sec(m.group("sec")) if m.group("sec") else ""
    ref = Ref(
        doc,
        q.resolve(conn, doc),
        sec,
        int(m.group("para")) if m.group("para") else None,
        m.group("pn") or "",
        int(m.group("a")) if m.group("a") else None,
        int(m.group("b")) if m.group("b") else None,
    )
    head = _heading_by_pn(conn, ref.served, ref.pn) if ref.pn else None
    if head is not None:
        # '#section-9.6' is a section anchor (html), not a paragraph
        ref.sec, ref.pn = head["sec_num"], ""
        if not ref.sec:  # unnumbered section: address it by lines
            ref.start, ref.end = head["start_line"], head["end_line"]
    elif ref.pn.startswith("section-") and not has_xml(conn, ref.served):
        m2 = re.fullmatch(r"section-(\d+(?:\.\d+)*)", ref.pn)
        if m2:  # txt-only doc, html-style section anchor
            ref.sec, ref.pn = m2.group(1), ""
    if ref.para is not None:
        if not ref.sec:
            raise RefError(f"¶ needs a section: e.g. '{doc}§9.6¶{ref.para}'")
        h = _heading(conn, ref.served, ref.sec)
        if h is None:
            raise RefError(
                f"{ref.served} is not paragraph-indexed (run `rfclib index "
                f"build`). Use a section or line ref instead."
            )
        ref.pn = f"{h['pn']}-{ref.para}"
        if not _block(conn, ref.served, ref.pn):
            n = conn.execute(
                "SELECT COUNT(*) FROM blocks WHERE doc_id=? AND pn LIKE ? AND kind<>'heading'",
                (ref.served, h["pn"] + "-%"),
            ).fetchone()[0]
            raise RefError(f"no ¶{ref.para} in {doc}§{ref.sec} (it has {n} top-level blocks)")
    elif ref.pn and not _block(conn, ref.served, ref.pn):
        raise RefError(f"no block #{ref.pn} in {ref.served}")
    return ref


# --------------------------------------------------------------------------
# lookups


def _block(conn, doc: str, pn: str):
    return conn.execute("SELECT * FROM blocks WHERE doc_id=? AND pn=?", (doc, pn)).fetchone()


def _heading(conn, doc: str, sec: str):
    return (
        conn.execute("SELECT * FROM blocks WHERE doc_id=? AND kind='heading' AND sec_num=?", (doc, sec)).fetchone()
        if sec
        else None
    )


def _heading_by_pn(conn, doc: str, pn: str):
    return conn.execute("SELECT * FROM blocks WHERE doc_id=? AND kind='heading' AND pn=?", (doc, pn)).fetchone()


def _blocks_in(conn, doc: str, a: int, b: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM blocks WHERE doc_id=? AND kind<>'heading' AND start_line>=? AND start_line<=? ORDER BY ord",
        (doc, a, b),
    ).fetchall()


def _frag(conn, doc: str, pn: str, sec: str) -> str:
    """URL fragment for a ref. Paragraph pn ids are real anchors only in
    RFCXML-rendered HTML (RFC 8650+); the RFC Editor's HTML for older RFCs
    anchors sections only, so their paragraphs link to the section."""
    if pn and conn.execute("SELECT 1 FROM files WHERE doc_id=? AND fmt='xml'", (doc,)).fetchone():
        return pn
    return _s.url_frag(sec) if sec else ""


def has_xml(conn, doc: str) -> bool:
    return conn.execute("SELECT 1 FROM blocks WHERE doc_id=? LIMIT 1", (doc,)).fetchone() is not None


def block_ref(doc: str, row) -> str:
    """'RFC9000§9.6¶3' when the block is a numbered paragraph of a numbered
    section, else 'RFC9000#<pn>'."""
    pn, sec = row["pn"], row["sec_num"]
    m = re.fullmatch(r"(section-.+)-(\d+)", pn)
    if sec and m and row["kind"] != "heading":
        return f"{doc}§{sec}¶{m.group(2)}"
    return f"{doc}#{pn}"


def sec_ref(doc: str, sec: str, a: int | None = None, b: int | None = None) -> str:
    if sec:
        return f"{doc}§{sec}"
    return f"{doc}:{a}-{b}" if a else doc


def _meta(conn, doc: str) -> dict:
    return q._row_to_meta(conn, q.get_doc_row(conn, doc))


def _doc_line(conn, ref: Ref, meta: dict) -> str:
    if meta["is_current"]:
        state = "current"
    else:
        direct = meta["relations"].get("obsoleted_by", [])
        now = current_successors(conn, ref.served)
        state = (
            "OBSOLETE, superseded by "
            + (", ".join(direct) or "?")
            + (f" (current: {', '.join(now)})" if now and set(now) != set(direct) else "")
        )
    via = f" (via {ref.doc})" if ref.doc != ref.served else ""
    rel = meta.get("relations") or {}
    # Document-level. A later RFC may change one section of a profile that
    # stays current; the read of that section has to say so before the quote.
    clause = _cite.relation_clause(rel)
    extra = f" | {clause}" if clause else ""
    return (
        f"{_cite.label(ref.served)}{via} — {meta.get('title') or ''} | "
        f"{meta.get('current_status') or meta.get('status') or ''} | "
        f"{(meta.get('pub_date') or '')[:7]} | {state}{extra}"
    )


def _clean_lines(lines: list[str], a: int, b: int) -> list[tuple[int, str]]:
    """(line_no, text) for [a, b] minus page furniture, blank runs -> one."""
    out: list[tuple[int, str]] = []
    blank = False
    for n in range(a, min(b, len(lines)) + 1):
        ln = lines[n - 1].replace("\f", "").rstrip()
        if any(p.search(ln) for p in _FURNITURE):
            continue
        if not ln.strip():
            if out and not blank:
                blank = True
            continue
        if blank:
            out.append((0, ""))
            blank = False
        out.append((n, ln))
    return out


def _text(conn, ref: Ref, mirror_root: Path) -> list[str]:
    text, _served, _p = q._served_text(conn, ref.served, "txt", mirror_root)
    if text is None:
        raise RefError(
            f"{ref.served} has no txt rendering locally or upstream", f"read('{ref.served}', format='html')"
        )
    return text.splitlines()


def _scope(conn, ref: Ref, total: int) -> tuple[int, int, str, str]:
    """(start, end, sec_num, sec_title) the ref addresses; a paragraph ref
    scopes to its enclosing section, starting at the paragraph."""
    if ref.pn:
        b = _block(conn, ref.served, ref.pn)
        h = _heading(conn, ref.served, b["sec_num"]) if b["sec_num"] else None
        if h is None:  # unnumbered section: run to the block's own section
            return b["start_line"], b["end_line"], b["sec_num"], b["sec_title"]
        return b["start_line"], h["end_line"], b["sec_num"], b["sec_title"]
    if ref.sec:
        span = q._resolve_section_arg(conn, ref.served, ref.sec)
        if not span.get("ok"):
            similar = ""
            if span.get("suggestions"):
                similar = "; similar: " + ", ".join(f"{ref.doc}§{x}" for x in span["suggestions"])
            raise RefError(f"no section {ref.sec} in {ref.served}{similar}", f"outline('{ref.doc}')")
        return (span["start_line"], span["end_line"], span["sec_num"], span.get("sec_title") or "")
    a = max(1, ref.start or 1)
    b = min(total, ref.end or total)
    if b < a:
        raise RefError(f"empty line range {a}-{b} ({ref.served} has {total} lines)")
    return a, b, "", ""


def _neighbours(conn, ref: Ref, sec: str, end: int) -> str:
    rows = _s.toc(conn, ref.served)
    nxt = next((r for r in rows if r["start_line"] > end and r["sec_num"]), None)
    bits = []
    if sec and "." in sec:
        bits.append(f"up: {ref.doc}§{sec.rsplit('.', 1)[0]}")
    if nxt:
        bits.append(f'after: {ref.doc}§{nxt["sec_num"]} "{nxt["title"]}"')
    return " | ".join(bits)


# --------------------------------------------------------------------------
# read


def read(
    conn: sqlite3.Connection,
    raw: str,
    *,
    mirror_root: Path,
    max_tokens: int = 2000,
    view: str = "text",
    lang: str | None = None,
) -> str:
    ref = parse_ref(conn, raw)
    view = (view or "text").lower()
    if view not in ("text", "normative", "code", "refs"):
        raise RefError("view must be text | normative | code | refs")
    if view == "refs":
        return links(conn, raw, direction="out")
    budget = max(400, int(max_tokens) * CHARS_PER_TOKEN)
    meta = _meta(conn, ref.served)
    if ref.is_doc() and view == "text":
        return _doc_overview(conn, ref, meta, mirror_root)
    lines = _text(conn, ref, mirror_root)
    a, b, sec, title = _scope(conn, ref, len(lines))
    head = _doc_line(conn, ref, meta)
    label = sec_ref(ref.doc, sec) if sec else f"{ref.doc}:{a}-{b}"
    frag = _frag(conn, ref.served, ref.pn, sec)
    errata = _cite.errata_note(conn, ref.served, sec)
    top = (
        f"{head}\n{label}" + (f' "{title}"' if title else "") + f" | lines {a}-{b} | {errata}\n"
        f"{q.anchor_url(meta, frag, ref.served)}\n"
    )
    if view == "normative":
        body, nxt = _normative(conn, ref, lines, a, b, budget)
    elif view == "code":
        body, nxt = _code(conn, ref, a, b, budget, lang)
    else:
        body, nxt = _page(conn, ref, lines, a, b, budget)
    foot = [f"next: {nxt}" if nxt else "end of scope"]
    nb = _neighbours(conn, ref, sec, b)
    if nb:
        foot.append(nb)
    return top + "\n" + body.rstrip() + "\n\n— " + " | ".join(foot)


def _page(conn, ref: Ref, lines: list[str], a: int, b: int, budget: int) -> tuple[str, str | None]:
    """Text of [a, b] up to budget, cut on unit boundaries.

    Units are RFCXML blocks (each preceded by a [§x¶n] marker, so every
    paragraph on the page is citable) and subsection headings; txt-only
    documents fall back to blank-line paragraphs. The next-page cursor is a
    ¶ ref while the page stays inside the scope's own section, else a line
    range to the end of the scope, so paging a section never stops at the
    end of its first subsection."""
    marks: dict[int, tuple[str, str]] = {}  # line -> (label, sec_num)
    if has_xml(conn, ref.served):
        for blk in _blocks_in(conn, ref.served, a, b):
            marks.setdefault(blk["start_line"], (block_ref(ref.doc, blk)[len(ref.doc) :], blk["sec_num"]))
        for h in conn.execute(
            "SELECT sec_num, start_line FROM blocks WHERE doc_id=? AND "
            "kind='heading' AND start_line>? AND start_line<=?",
            (ref.served, a, b),
        ):
            marks[h["start_line"]] = ("", h["sec_num"])
    units: list[tuple[str | None, str, list[tuple[int, str]]]] = []
    for n, ln in _clean_lines(lines, a, b):
        if not units or n in marks or (not marks and n == 0):
            lab, sec = marks.get(n, (None, ""))
            units.append((lab, sec, []))
        units[-1][2].append((n, ln))
    own_sec = ref.sec or (_block(conn, ref.served, ref.pn)["sec_num"] if ref.pn else "")
    out: list[str] = []
    size = 0
    for lab, sec, ls in units:
        first = next((n for n, _ in ls if n), b)
        usize = sum(len(x) + 1 for _, x in ls)
        if out and size + usize > budget:
            if lab and sec == own_sec:
                return "\n".join(out), f"{ref.doc}{lab}"
            return "\n".join(out), (f"{ref.doc}:{first}-{b}" + (f" (starts at {lab or '§' + sec})" if sec else ""))
        if lab:
            out.append(f"[{lab}]")
        for n, x in ls:
            if out and size + len(x) > budget * 1.5 and n:
                # one unit bigger than a page (giant table/figure): lines
                return "\n".join(out), f"{ref.doc}:{n}-{b}"
            out.append(x)
            size += len(x) + 1
    return "\n".join(out), None


def _cursor(conn, ref: Ref, row, b: int) -> str:
    """Next-page ref for block `row`: its own ref while it belongs to the
    scope's section (a block ref scopes to its OWN section, so a block in a
    subsection would end the paging early), else a line range to b."""
    own = ref.sec or (_block(conn, ref.served, ref.pn)["sec_num"] if ref.pn else None)
    if own is not None and row["sec_num"] == own:
        return block_ref(ref.doc, row)
    return f"{ref.doc}:{row['start_line']}-{b}"


def _normative(conn, ref: Ref, lines, a, b, budget):
    out, size = [], 0
    if has_xml(conn, ref.served):
        rows = [r for r in _blocks_in(conn, ref.served, a, b) if r["bcp14"]]
        for r in rows:
            item = f"[{block_ref(ref.doc, r)}] ({r['bcp14']}) {r['text']}"
            if out and size + len(item) > budget:
                return "\n\n".join(out), _cursor(conn, ref, r, b) + " (view=normative)"
            out.append(item)
            size += len(item) + 2
        if not out:
            return "(no BCP 14 keywords in this scope)", None
        return "\n\n".join(out), None
    # txt-only: uppercase keyword sentences (RFC 2119 convention; older
    # documents may use the words loosely)
    text = " ".join(t for _n, t in _clean_lines(lines, a, b) if t)
    text = re.sub(r"\s+", " ", text)
    for sent in re.split(r"(?<=[.;:])\s+(?=[A-Z(\"])", text):
        found = sorted(set(NORM_RE.findall(sent)))
        if not found:
            continue
        item = f"({','.join(found)}) {sent.strip()}"
        if out and size + len(item) > budget:
            return "\n\n".join(out) + "\n[more; narrow the ref]", None
        out.append(item)
        size += len(item) + 2
    return ("\n\n".join(out) if out else "(no uppercase BCP 14 keywords in this scope)"), None


def _code(conn, ref: Ref, a, b, budget, lang):
    if not has_xml(conn, ref.served):
        raise RefError(
            f"view=code needs paragraph blocks; {ref.served} "
            "is not indexed yet. Use grep(doc, pattern) or read "
            "the section text."
        )
    rows = [
        r
        for r in _blocks_in(conn, ref.served, a, b)
        if r["kind"] in ("sourcecode", "artwork") and (not lang or r["lang"].lower() == lang.lower())
    ]
    if not rows:
        langs = sorted(
            {
                r["lang"]
                for r in conn.execute(
                    "SELECT DISTINCT lang FROM blocks WHERE doc_id=? AND kind='sourcecode'", (ref.served,)
                )
                if r["lang"]
            }
        )
        return (
            "(no code/figures in this scope" + (f"; this doc has: {', '.join(langs)}" if langs else "") + ")"
        ), None
    out, size = [], 0
    for r in rows:
        item = (
            f"[{block_ref(ref.doc, r)}] {r['kind']}"
            + (f" type={r['lang']}" if r["lang"] else "")
            + f" L{r['start_line']}-{r['end_line']}\n{r['text']}"
        )
        if out and size + len(item) > budget:
            return "\n\n".join(out), _cursor(conn, ref, r, b) + " (view=code)"
        out.append(item)
        size += len(item) + 2
    return "\n\n".join(out), None


def _doc_overview(conn, ref: Ref, meta: dict, mirror_root: Path) -> str:
    abstract = re.sub(r"\s+", " ", meta.get("abstract") or "").strip()
    out = [_doc_line(conn, ref, meta), q._url_of(meta), ""]
    if abstract:
        out += [abstract[:900] + ("…" if len(abstract) > 900 else ""), ""]
    out.append(outline(conn, ref.doc, depth=1, header=False))
    return "\n".join(out)


# --------------------------------------------------------------------------
# outline


def outline(
    conn: sqlite3.Connection,
    doc: str,
    depth: int | None = 2,
    contains: str | None = None,
    header: bool = True,
    max_rows: int = 200,
) -> str:
    _require_library(conn)
    try:
        did = q.normalize_doc_id(doc)
        q.get_doc_row(conn, did)
    except (ValueError, q.NotFound) as e:
        raise RefError(f"unknown document {doc!r}: {e}") from None
    served = q.resolve(conn, did)
    _ensure_text(conn, served)
    all_rows = _s.toc(conn, served, contains=contains)
    if not all_rows:
        if contains and _s.toc(conn, served):
            raise RefError(
                f"no section of {served} has {contains!r} in its number or title",
                f"outline('{did}') without contains, or grep('{did}', {contains!r})",
            )
        raise RefError(f"{served} is not section-indexed yet", action="rfclib index build")
    want = None if contains else depth  # a filter searches every level
    rows = [r for r in all_rows if want is None or not r["sec_num"] or r["sec_num"].count(".") + 1 <= want]
    note = ""
    while len(rows) > max_rows and (want or 9) > 1:
        want = (want or 9) - 1
        rows = [r for r in all_rows if not r["sec_num"] or r["sec_num"].count(".") + 1 <= want]
        note = f" (reduced to depth {want} to fit; pass depth=None or contains=)"
    out = []
    if header:
        meta = _meta(conn, served)
        out.append(_doc_line(conn, Ref(did, served), meta))
    out.append(f"{len(rows)} of {len(all_rows)} sections, depth {want if want else 'all'}{note}")
    for r in rows:
        sn = r["sec_num"]
        ind = "  " * sn.count(".") if sn and not sn.startswith("Appendix") else ""
        tag = f"§{sn} " if sn else ""
        extra = " (no own text; spans its subsections)" if r.get("parts") == 0 else ""
        out.append(f"{ind}{tag}{r['title']}  L{r['start_line']}-{r['end_line']}{extra}")
    out.append(f"read: read('{did}§<num>')  | unnumbered: read('{did}:<a>-<b>')")
    return "\n".join(out)


# --------------------------------------------------------------------------
# grep


def grep(
    conn: sqlite3.Connection,
    doc: str,
    pattern: str,
    *,
    mirror_root: Path,
    max_hits: int = 25,
    ignore_case: bool = True,
) -> str:
    ref = parse_ref(conn, doc)
    try:
        rx = re.compile(pattern, re.I if ignore_case else 0)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I if ignore_case else 0)
    lines = _text(conn, ref, mirror_root)
    a, b = 1, len(lines)
    if not ref.is_doc():
        a, b, _sec, _t = _scope(conn, ref, len(lines))
    blocks = _blocks_in(conn, ref.served, 1, len(lines)) if has_xml(conn, ref.served) else []
    bstarts = [r["start_line"] for r in blocks]
    marks = [
        (r["start_line"], r["sec_num"])
        for r in conn.execute(
            "SELECT DISTINCT start_line, sec_num FROM chunks WHERE doc_id=? ORDER BY start_line", (ref.served,)
        )
    ]
    mstarts = [m[0] for m in marks]

    def where(n: int) -> str:
        i = bisect.bisect_right(bstarts, n) - 1
        if i >= 0 and blocks[i]["end_line"] >= n:
            return block_ref(ref.doc, blocks[i])
        j = bisect.bisect_right(mstarts, n) - 1
        if j >= 0 and marks[j][1]:
            return f"{ref.doc}§{marks[j][1]}"
        return f"{ref.doc}:{n}"

    hits, out = 0, []
    for n in range(a, b + 1):
        ln = lines[n - 1]
        if any(p.search(ln) for p in _FURNITURE) or not rx.search(ln):
            continue
        hits += 1
        if len(out) < max_hits:
            out.append(f"{where(n)} L{n}: {ln.strip()[:160]}")
    if not hits:
        return (
            f"no match for /{pattern}/ in {ref.doc}"
            + ("" if ref.is_doc() else f" lines {a}-{b}")
            + ". Try search_all for the whole corpus."
        )
    more = f"\n[{hits - len(out)} more; narrow the pattern or scope]" if hits > len(out) else ""
    return f"{hits} match(es) in {ref.doc}\n" + "\n".join(out) + more


# --------------------------------------------------------------------------
# cite


def cite(conn: sqlite3.Connection, raw: str, *, mirror_root: Path, style: str = "verbose") -> str:
    ref = parse_ref(conn, raw)
    if not ref.pn:
        sec = ref.sec or None
        lines = f"{ref.start}-{ref.end or ref.start}" if ref.start else None
        out = _cite.cite(conn, ref.doc, section=sec, lines=lines, style=style, mirror_root=mirror_root)
        if out.startswith("CANNOT CITE"):
            raise RefError(out)
        return out
    blk = _block(conn, ref.served, ref.pn)
    meta = _meta(conn, ref.doc)
    br = block_ref(ref.doc, blk)
    short = _cite.label(ref.doc) + br[len(ref.doc) :]
    url = q.anchor_url(meta, _frag(conn, ref.served, ref.pn, blk["sec_num"]), ref.served)
    if style == "short":
        return short
    if style == "markdown":
        return f"[{short}]({url})"
    if style == "bibtex":
        return _cite.cite(conn, ref.doc, style="bibtex")
    body, _ = _cite.span_text(
        conn, ref.served, mirror_root=mirror_root, lines=f"{blk['start_line']}-{blk['end_line']}"
    )
    status = meta.get("current_status") or meta.get("status") or ""
    successor = ", ".join(meta["relations"].get("obsoleted_by", []))
    state = "current" if meta["is_current"] else f"OBSOLETE by {successor or 'unknown'}"
    clause = _cite.relation_clause(meta["relations"])
    state = f"{state} | {clause}" if clause else state
    sec_t = f' "{blk["sec_title"]}"' if blk["sec_title"] else ""
    tail = (
        f"{short}{sec_t} lines {blk['start_line']}-{blk['end_line']} — "
        f"{meta.get('title') or ''} ({(meta.get('pub_date') or '')[:7]}, "
        f"{status}, {state})\n{url} | "
        f"{_cite.errata_note(conn, ref.served, blk['sec_num'])} | "
        f"span sha256:{q.span_hash(body)}"
    )
    if style == "comment":
        return "\n".join("# " + ln for ln in tail.split("\n"))
    return tail


# --------------------------------------------------------------------------
# links


def links(conn: sqlite3.Connection, raw: str, direction: str = "out", limit: int = 30) -> str:
    ref = parse_ref(conn, raw)
    direction = (direction or "out").lower()
    if direction == "related":
        from . import subjects as subj_mod

        if not subj_mod.subjects_ready(conn):
            raise RefError("the subject tree is not in the library yet", action="rfclib subjects sync")
        r = subj_mod.related(conn, ref.served, limit=limit)
        subs = ", ".join(s.get("name", "") for s in r.get("subjects", []))
        out = [f"{ref.served} subjects: {subs or '(none)'}", "documents sharing subjects:"]
        for d in r.get("nearby_docs", [])[:limit]:
            out.append(f"  {d.get('doc_id')} — {d.get('title') or ''} ({d.get('shared_subjects')} shared)")
        return "\n".join(out)
    if direction not in ("out", "in"):
        raise RefError("direction must be out | in | related")
    sec = ref.sec
    if ref.pn:
        blk = _block(conn, ref.served, ref.pn)
        sec = blk["sec_num"]
    like = f"{sec}.%"
    if direction == "out":
        q_ = "SELECT dst_doc peer, dst_sec psec, src_sec ssec, normative FROM xrefs WHERE doc_id=?"
        args: list = [ref.served]
        if ref.pn:
            q_ += " AND src_pn=?"
            args.append(ref.pn)
        elif sec:
            q_ += " AND (src_sec=? OR src_sec LIKE ?)"
            args += [sec, like]
    else:
        q_ = "SELECT doc_id peer, src_sec psec, dst_sec ssec, normative FROM xrefs WHERE dst_doc=?"
        args = [ref.served]
        if sec:
            q_ += " AND (dst_sec=? OR dst_sec LIKE ?)"
            args += [sec, like]
    rows = conn.execute(q_, args).fetchall()
    agg: dict[str, dict] = {}
    for r in rows:
        e = agg.setdefault(r["peer"], {"psec": set(), "ssec": set(), "norm": False})
        if r["psec"]:
            e["psec"].add(r["psec"])
        if r["ssec"]:
            e["ssec"].add(r["ssec"])
        e["norm"] |= bool(r["normative"])
    scope = sec_ref(ref.doc, sec) if sec else ref.doc
    out = []
    if agg:
        info = {
            d["doc_id"]: d
            for d in conn.execute(
                "SELECT doc_id, title, current_status, is_current FROM docs "
                "WHERE doc_id IN (%s)" % ",".join("?" * len(agg)),
                list(agg),
            )
        }
        order = sorted(agg, key=lambda p: (not agg[p]["norm"], -len(agg[p]["psec"]), p))
        verb = "cites" if direction == "out" else "is cited by"
        out.append(f"{scope} {verb} {len(agg)} document(s) (section-precise):")
        for p in order[:limit]:
            e, d = agg[p], info.get(p, {})
            psecs = ", ".join(f"§{s}" for s in sorted(e["psec"], key=_s_key)[:8])
            ssecs = ", ".join(f"§{s}" for s in sorted(e["ssec"], key=_s_key)[:6])
            cur = "" if not d or d["is_current"] else " OBSOLETE"
            if d and not d["title"]:  # BCP/STD/FYI alias row
                d = dict(d, title=f"(series alias of {q.resolve(conn, p)})")
            if direction == "out":
                out.append(
                    f"  {p} {psecs or '(whole doc)'}"
                    f"{' [normative]' if e['norm'] else ''} — "
                    f"{(d['title'] if d else '') or ''}{cur}" + (f"  ← from {ssecs}" if ssecs and not sec else "")
                )
            else:
                out.append(f"  {p} {psecs or ''} → {ssecs or '(whole doc)'} — {(d['title'] if d else '') or ''}{cur}")
        if len(agg) > limit:
            out.append(f"  … {len(agg) - limit} more")
    # whole-document citation graph mined from txt (all eras)
    if not sec:
        from . import graph as ref_graph

        g = ref_graph.get_refs(conn, ref.served, limit=limit)
        side = g["outbound"] if direction == "out" else g["inbound"]
        rest = [x for x in side if x["doc_id"] not in agg]
        if rest:
            out.append(f"{'cites' if direction == 'out' else 'cited by'} (reference lists, {len(rest)} more):")
            for x in rest[:limit]:
                secs = " §" + ", §".join(x["sections"][:5]) if x["sections"] else ""
                out.append(
                    f"  {x['doc_id']}{secs} [{'/'.join(x['kinds'])}]"
                    f" — {x['title'] or ''}" + ("" if x["is_current"] else " OBSOLETE")
                )
    if not out:
        return f"no section-level citations recorded for {scope}" + (
            "" if has_xml(conn, ref.served) else " (try without a section for reference-list edges)"
        )
    return "\n".join(out)


def _s_key(s: str):
    return [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"[.\s]", s)]


# --------------------------------------------------------------------------
# browse (subject taxonomy) and errata, as compact text


def subjects_tree(
    conn: sqlite3.Connection, parent: str | None = None, contains: str | None = None, limit: int = 120
) -> str:
    """One level of the RFC Editor subject tree (default: the ~19 roots),
    or every subject matching `contains` with its path. Each line carries
    the slug to pass on and the document count."""
    from . import subjects as subj_mod

    if not subj_mod.subjects_ready(conn):
        raise RefError("the subject tree is not in the library yet", action="rfclib subjects sync")
    kids = {r["parent"]: r["n"] for r in conn.execute("SELECT parent, COUNT(*) n FROM subjects GROUP BY parent")}

    def line(r, ind=""):
        k = kids.get(r["slug"], 0)
        return f"{ind}{r['slug']} — {r['name']} ({r['doc_count'] or 0} docs" + (f", {k} subtopics" if k else "") + ")"

    if contains:
        rows = subj_mod.list_subjects(conn, contains=contains, limit=limit)
        if not rows:
            raise RefError(f"no subject matches {contains!r}", "browse() lists the top level")
        par = {r["slug"]: r["parent"] for r in conn.execute("SELECT slug, parent FROM subjects")}
        out = [f"{len(rows)} subject(s) matching {contains!r}:"]
        for r in rows:
            path, p = [], r["parent"]
            while p and len(path) < 6:
                path.append(p)
                p = par.get(p)
            out.append(line(r) + (f"  [in {' > '.join(reversed(path))}]" if path else ""))
        return "\n".join(out)
    if parent:
        row = conn.execute(
            "SELECT slug FROM subjects WHERE slug=? OR lower(name)=lower(?)", (parent, parent)
        ).fetchone()
        if row is None:
            raise RefError(f"unknown subject {parent!r}", f"browse(contains={parent!r})")
        parent = row["slug"]
    rows = conn.execute(
        "SELECT * FROM subjects WHERE "
        + ("parent=?" if parent else "(parent IS NULL OR parent='')")
        + " ORDER BY ord, name",
        (parent,) if parent else (),
    ).fetchall()
    head = f"subtopics of {parent}:" if parent else f"RFC Editor subject tree, top level ({len(rows)} roots):"
    tail = (
        "browse(subject='<slug>') lists documents; "
        "browse(parent='<slug>') goes one level down; "
        "browse(contains='http') searches names"
    )
    return "\n".join([head] + [line(r, "  ") for r in rows[:limit]] + [tail])


def subject_docs(
    conn: sqlite3.Connection, subject: str, offset: int = 0, limit: int = 30, include_obsolete: bool = False
) -> str:
    from . import subjects as subj_mod

    try:
        g = subj_mod.get_subject(conn, subject, include_obsolete=include_obsolete, limit=limit, offset=offset)
    except subj_mod.SubjectNotFound as e:
        raise RefError(str(e), f"browse(contains={subject!r})") from None
    s = g["subject"]
    out = [
        f"{s['slug']} — {s['name']}: {g['docs_total']} document(s)"
        + (" incl. subtopics" if g.get("children") else "")
        + ("" if include_obsolete else ", current only")
    ]
    if s.get("description"):
        out.append(s["description"])
    if g.get("children"):
        out.append(
            "subtopics: " + ", ".join(c["slug"] if isinstance(c, dict) else str(c) for c in g["children"][:25])
        )
    for d in g["docs"]:
        out.append(
            f"  {d['doc_id']} — {d['title']} | {d.get('current_status') or ''} | {(d.get('pub_date') or '')[:7]}"
        )
    if g.get("next_offset") is not None:
        out.append(f"next: browse(subject='{s['slug']}', offset={g['next_offset']})")
    return "\n".join(out)


def errata_text(
    conn: sqlite3.Connection, doc: str, status: str = "verified", section: str | None = None, max_tokens: int = 2000
) -> str:
    """Errata for a document as compact text: verified only by default,
    each with section, type, and the corrected text."""
    from . import errata as errata_mod

    ref = parse_ref(conn, doc, need_text=False)
    section = section or ref.sec or None  # 'RFC791§3.1' narrows too
    res = errata_mod.ensure(conn, ref.served)
    rows = res["results"]
    want = (status or "verified").lower()
    sel = [
        e
        for e in rows
        if want == "all"
        or e["status"].lower() == want
        or (want == "open" and e["status"] in ("Reported", "Held for Document Update"))
    ]
    if section:
        sec = _s.norm_sec(section)
        sel = [e for e in sel if sec and sec in (e.get("section") or "")]
    counts: dict[str, int] = {}
    for e in rows:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "none"
    out = [f"errata for {ref.served}: {summary} (source {res.get('source')}, {(res.get('fetched_at') or '')[:10]})"]
    if not sel:
        out.append(f"(no {want} errata" + (f" on §{section}" if section else "") + ")")
        return "\n".join(out)
    budget, size = max(400, max_tokens * CHARS_PER_TOKEN), 0
    for e in sel:

        def clip(t, n=700):
            t = (t or "").strip()
            return t if len(t) <= n else t[:n] + " …"

        item = (
            f"\n[eid {e['eid']}] {e['status']} {e.get('type') or ''} — "
            f"section: {(e.get('section') or '?').strip()[:60]}\n"
            f"  says: {clip(e.get('says'))}\n"
            f"  should say: {clip(e.get('should_say'))}"
            + (f"\n  notes: {clip(e.get('notes'), 300)}" if e.get("notes") else "")
        )
        if size + len(item) > budget and size:
            out.append(f"\n[{len(sel) - sel.index(e)} more; pass section= or a larger max_tokens]")
            break
        out.append(item)
        size += len(item)
    out.append(f"\nhttps://www.rfc-editor.org/errata/{ref.served.lower()}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# search and info, as compact text

_MARK = re.compile(r">>>(.+?)<<<")


def _hit_ref(conn, h: dict) -> tuple[str, str]:
    """(paragraph-precise ref, section ref) for a section hit: the block of
    the section that carries most of the snippet's highlighted terms."""
    doc = h["doc_id"]
    sec = f"{doc}§{h['sec_num']}" if h.get("sec_num") else f"{doc}:{h['start_line']}-{h['end_line']}"
    terms = {t.lower() for t in _MARK.findall(h.get("snippet") or "")}
    best, n_best = None, 0
    if terms:
        for b in conn.execute(
            "SELECT pn, kind, sec_num, text FROM blocks WHERE doc_id=? "
            "AND kind<>'heading' AND start_line BETWEEN ? AND ? "
            "ORDER BY ord",
            (doc, h["start_line"], h["end_line"]),
        ):
            low = b["text"].lower()
            n = sum(1 for t in terms if t in low)
            if n > n_best:
                best, n_best = b, n
    return (block_ref(doc, best) if best is not None else sec), sec


def _status_tag(row: dict) -> str:
    st = row.get("current_status") or ""
    cur = row.get("is_current", 1)
    obs = row.get("obsoleted_by") or (row.get("relations") or {}).get("obsoleted_by", [])
    tag = st + (", current" if cur else ", OBSOLETE" + (f" by {', '.join(obs)}" if obs else ""))
    return tag


_STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "when",
    "which",
    "with",
    "both",
    "must",
    "should",
    "can",
}


def _title_noise(query: str, h: dict) -> bool:
    """A hit backed only by a document-title match whose title covers less
    than half of the query's content words ('Content-Centric Networking'
    for 'Content-Length'): hybrid fusion surfaces these Abstracts, but they
    are noise unless the document is plausibly what the query is about."""
    if (h.get("sources") or "") != "title":
        return False
    words = [w for w in re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", query.lower()) if w not in _STOP]
    if not words:
        return False
    title = set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", (h.get("title") or "").lower()))
    return sum(1 for w in words if w in title) * 2 <= len(words)


def search_text(
    conn: sqlite3.Connection,
    query: str,
    *,
    scope: str = "sections",
    mode: str = "hybrid",
    limit: int = 8,
    include_obsolete: bool = False,
    subject: str | None = None,
    status: str | None = None,
    stream: str | None = None,
    detail: str = "concise",
) -> str:
    from . import library
    from .index import embed as ix_embed, hybrid as ix_hybrid

    _require_library(conn)
    scope, mode = (scope or "sections").lower(), (mode or "hybrid").lower()
    limit = max(1, min(int(limit), 30))
    detailed = (detail or "").lower() == "detailed"
    if scope in ("documents", "docs", "rfcs") or subject or status or stream:
        from . import subjects as subj_mod

        try:
            hits = q.search(
                conn,
                query,
                limit=limit,
                include_obsolete=include_obsolete,
                stream=stream,
                status=status,
                subject=subject,
            )
        except subj_mod.SubjectNotFound as e:
            raise RefError(str(e), f"browse(contains={subject!r})") from None
        if not hits:
            return (
                f"no documents match {query!r}"
                + (f" in subject {subject!r}" if subject else "")
                + ". Try scope='sections' or fewer words."
            )
        out = [f"{len(hits)} document(s) for {query!r}:"]
        for i, h in enumerate(hits, 1):
            subs = ", ".join(s["name"] for s in h.get("subjects", [])[:3])
            out.append(
                f"{i}. {h['doc_id']} — {h['title']} | "
                f"{_status_tag(h)} | {(h.get('pub_date') or '')[:7]}" + (f" | {subs}" if subs and detailed else "")
            )
        out.append("next: read('<doc>') for abstract + outline")
        return "\n".join(out)
    try:
        if mode in ("exact", "bm25", "fts"):
            hits = _s.search_chunks(conn, query, limit=limit, include_obsolete=include_obsolete)
        elif mode in ("semantic", "knn", "concept"):
            hits = ix_embed.semantic_search(conn, query, limit=limit, include_obsolete=include_obsolete)
        else:
            hits = ix_hybrid.hybrid_search(conn, query, limit=limit + 6, include_obsolete=include_obsolete)
    except Exception as e:  # noqa: BLE001 - index missing or FTS syntax
        raise RefError(
            f"search failed ({e})",
            "mode='exact' takes FTS5 syntax: quoted phrases, AND/OR, prefix*, NEAR(a b, 40)",
            "rfclib index build (and rfclib index embed for mode='semantic')",
        ) from None
    hits = [h for h in hits if not _title_noise(query, h)][:limit]
    if not hits:
        note = library.coverage_note(conn)
        return ((note + "\n") if note else "") + (
            f"no sections match {query!r}. Try mode='semantic' for a paraphrase, or scope='documents'."
        )
    out = [f"{len(hits)} section hit(s) for {query!r} (mode={mode}):"]
    note = library.coverage_note(conn)
    if note:
        out.insert(0, note)
    for i, h in enumerate(hits, 1):
        ref, sec = _hit_ref(conn, h)
        snip = re.sub(r"\s+", " ", (h.get("snippet") or "")).strip()
        title = h.get("sec_title") or ""
        line = f'{i}. {ref} "{title}" — {h.get("title") or ""} | {_status_tag(h)}'
        if detailed:
            line += (
                f" | L{h['start_line']}-{h['end_line']}"
                + (f" | {h['sources']}" if h.get("sources") else "")
                + (f" | section {sec}" if sec != ref else "")
            )
        out.append(line)
        if snip:
            out.append("   " + snip[:220])
    out.append("next: read('<ref>') — each page ends with the ref to continue from")
    return "\n".join(out)


def info_text(conn: sqlite3.Connection, doc: str) -> str:
    """Bibliographic record + status graph + aliases + errata summary."""
    _require_library(conn)
    try:
        did = q.normalize_doc_id(doc)
        meta = q.get_metadata(conn, did)
    except (ValueError, q.NotFound) as e:
        raise RefError(f"unknown document {doc!r}: {e}") from None
    rel = meta["relations"]
    served = q.resolve(conn, did)
    out = [f"{_cite.label(did)} — {meta.get('title') or '(series alias)'}"]
    if meta.get("alias_of"):
        out.append(
            "is: " + "; ".join(f'{a["doc_id"]} "{a.get("title")}" ({_status_tag(a)})' for a in meta["alias_of"])
        )
    fields = [
        (
            "status",
            f"{meta.get('current_status') or ''}"
            + (
                f" (published as {meta['status']})"
                if meta.get("status") and meta.get("status") != meta.get("current_status")
                else ""
            ),
        ),
        ("state", "current" if meta["is_current"] else "OBSOLETE"),
        ("published", (meta.get("pub_date") or "")[:7]),
        ("authors", ", ".join(a if isinstance(a, str) else (a.get("name") or "") for a in meta.get("authors") or [])),
        ("stream", " / ".join(x for x in (meta.get("stream"), meta.get("wg"), meta.get("area")) if x)),
        ("doi", meta.get("doi") or ""),
    ]
    for k in ("obsoleted_by", "obsoletes", "updated_by", "updates", "alias"):
        if rel.get(k):
            fields.append((k.replace("_", " "), ", ".join(rel[k])))
    subs = ", ".join(s["name"] for s in meta.get("subjects", []))
    if subs:
        fields.append(("subjects", subs))
    fields.append(("errata", _cite.errata_note(conn, served).removeprefix("errata: ")))
    fields.append(("url", q._url_of(meta)))
    out += [f"{k}: {v}" for k, v in fields if v]
    ab = re.sub(r"\s+", " ", meta.get("abstract") or "").strip()
    if ab:
        out.append("abstract: " + (ab[:700] + "…" if len(ab) > 700 else ab))
    if not meta["is_current"] and rel.get("obsoleted_by"):
        now = current_successors(conn, did)
        if now:
            out.append(
                f"→ current replacement: {', '.join(now)}"
                + (f" (via {', '.join(rel['obsoleted_by'])})" if set(now) != set(rel["obsoleted_by"]) else "")
                + f"; read('{now[0]}')"
            )
    return "\n".join(out)


def current_successors(conn: sqlite3.Connection, doc: str) -> list[str]:
    """Follow obsoleted_by until current documents: RFC2616 -> RFC7230..7235
    (themselves obsolete) -> RFC9110, RFC9111, RFC9112."""
    seen, frontier, out = {doc}, [doc], []
    while frontier:
        nxt = []
        for d in frontier:
            for r in conn.execute(
                "SELECT DISTINCT r.src AS s, x.is_current AS cur FROM "
                "doc_relations r JOIN docs x ON x.doc_id = r.src WHERE "
                "r.dst=? AND r.kind='obsoletes' UNION SELECT DISTINCT "
                "r.dst, x.is_current FROM doc_relations r JOIN docs x ON "
                "x.doc_id = r.dst WHERE r.src=? AND r.kind='obsoleted_by'",
                (d, d),
            ):
                if r[0] in seen:
                    continue
                seen.add(r[0])
                (out if r[1] else nxt).append(r[0])
        frontier = nxt
    return sorted(set(out), key=lambda x: (x[:3], int(x[3:]) if x[3:].isdigit() else 0))


def recent_text(conn: sqlite3.Connection, limit: int = 15, series: str = "RFC") -> str:
    rows = q.list_recent(conn, n=limit, series=series)
    return "\n".join(
        [f"{len(rows)} most recent {series} documents:"]
        + [
            f"  {r['doc_id']} — {r['title']} | {r.get('current_status') or ''} | {(r.get('pub_date') or '')[:7]}"
            for r in rows
        ]
    )
