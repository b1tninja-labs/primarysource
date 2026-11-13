"""Full-text retrieval over section chunks (FTS5/BM25) + table of contents."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..sync.state import file_path, mirror_of
from .chunker import sha256_text, split_sections

# Reference/boilerplate sections match every vague query and pollute result
# lists: shared discount pattern used by both rankings (never drops rows).
NOISE_TITLE_RE = re.compile(
    r"\b(references?|acknowledg\w*|authors?|contributors?|participants|"
    r"editors'? address\w*|table of contents|change log|copyright)\b", re.I)


def _doc_sections(conn: sqlite3.Connection, doc_id: str, text: str,
                  xml_path: Path | None, stats: dict) -> list:
    """Sections for one document: RFCXML structure when the doc has XML
    (exact boundaries, aligned back onto txt lines), else the ToC-driven
    txt segmenter (txtseg); the legacy heuristic only if both fail. Also
    refreshes the doc's `blocks`/`xrefs`/`seg_quality` rows."""
    from . import rfcxml, txtseg
    for t in ("blocks", "xrefs", "seg_quality"):
        conn.execute(f"DELETE FROM {t} WHERE doc_id=?", (doc_id,))

    def quality(method: str, q=None, notes: str = ""):
        conn.execute(
            "INSERT INTO seg_quality(doc_id, method, toc_entries, matched, "
            "extra, headings, score, notes) VALUES(?,?,?,?,?,?,?,?)",
            (doc_id, method, q.toc_entries if q else 0,
             q.matched if q else 0, q.extra if q else 0,
             q.headings if q else 0, q.score if q else None,
             notes or ("; ".join(q.notes) if q else "")))

    px = lines = None
    if xml_path and Path(xml_path).exists():
        try:
            px = rfcxml.parse(Path(xml_path).read_text(
                encoding="utf-8", errors="replace"), doc_id)
            lines = rfcxml.align(px, text)
            stats["xml_docs"] += 1
            quality("rfcxml")
        except Exception as e:  # noqa: BLE001 - fall back, never block a build
            stats["xml_failed"] += 1
            stats.setdefault("xml_errors", []).append(
                f"{doc_id}: {type(e).__name__}: {e}"[:160])
            px = None
    if px is None:
        try:
            px, q = txtseg.segment(text, doc_id)
            lines = text.lstrip("﻿").splitlines()
            stats["txtseg_docs"] += 1
            quality(q.method, q)
        except Exception as e:  # noqa: BLE001
            stats.setdefault("txtseg_errors", []).append(
                f"{doc_id}: {type(e).__name__}: {e}"[:160])
            quality("legacy", notes=f"txtseg failed: {type(e).__name__}")
            return split_sections(text)
    conn.executemany(
        "INSERT OR REPLACE INTO blocks(doc_id, pn, ord, kind, sec_num, "
        "sec_title, sec_anchor, start_line, end_line, text, bcp14, lang, "
        "exact) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rfcxml.blocks_rows(px))
    conn.executemany(
        "INSERT OR REPLACE INTO xrefs(doc_id, src_pn, src_sec, dst_doc, "
        "dst_sec, ref_anchor, normative) VALUES(?,?,?,?,?,?,?)",
        rfcxml.xref_rows(px))
    return rfcxml.xml_sections(px, lines)


def _src_sha(txt_sha: str, xml_sha: str | None) -> str:
    """Source hash a document's chunks are built from: txt + xml + the
    parser that read them, so a parser fix re-chunks exactly its docs."""
    from .rfcxml import PARSER_VERSION
    from .txtseg import VERSION as TXTSEG_VERSION
    if xml_sha:
        return sha256_text(f"{txt_sha}:{xml_sha}:rfcxml-{PARSER_VERSION}")
    return sha256_text(f"{txt_sha}:txtseg-{TXTSEG_VERSION}")


def _index_one(conn: sqlite3.Connection, doc_id: str, path: Path,
               src_sha: str, xml_path: Path | None, stats: dict,
               fts_incremental: bool) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    # content-addressed id carryover: a re-chunk keeps the old id for
    # every section whose body hash is unchanged, so its embedding
    # stays valid (embed_state is keyed by chunk_id + content sha);
    # only genuinely new sections take fresh ids.
    old_ids: dict[str, list[int]] = {}
    for o in conn.execute("SELECT id, sha256 FROM chunks WHERE doc_id=?",
                          (doc_id,)).fetchall():
        old_ids.setdefault(o["sha256"], []).append(o["id"])
    next_id = (conn.execute("SELECT MAX(id) FROM chunks")
               .fetchone()[0] or 0) + 1
    taken: set[int] = set()
    plan: list[tuple[int, object, str]] = []
    for s in _doc_sections(conn, doc_id, text, xml_path, stats):
        sh = sha256_text(s.text)
        sid = next((i for i in old_ids.get(sh, ()) if i not in taken), None)
        if sid is None:
            sid = next_id
            next_id += 1
        taken.add(sid)
        plan.append((sid, s, sh))
    stale = [i for ids in old_ids.values() for i in ids if i not in taken]
    conn.executemany("DELETE FROM embed_state WHERE chunk_id=?",
                     [(i,) for i in stale])
    if fts_incremental:  # external-content FTS needs the old values to delete
        conn.execute(
            "INSERT INTO chunks_fts(chunks_fts, rowid, sec, body) "
            "SELECT 'delete', id, sec, body FROM chunks WHERE doc_id=?",
            (doc_id,))
    conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    for sid, s, sh in plan:
        conn.execute(
            "INSERT INTO chunks(id, doc_id, sec_num, sec_title, "
            "start_line, end_line, body, sha256) VALUES(?,?,?,?,?,?,?,?)",
            (sid, doc_id, s.sec_num, s.sec_title, s.start_line,
             s.end_line, s.text, sh))
    if fts_incremental:
        conn.execute(
            "INSERT INTO chunks_fts(rowid, sec, body) "
            "SELECT id, sec, body FROM chunks WHERE doc_id=?", (doc_id,))
    from .lexical import index_identifiers
    reused = {i for ids in old_ids.values() for i in ids}
    index_identifiers(conn, [sid for sid, _s, _h in plan if sid not in reused],
                      drop_ids=stale)
    conn.execute(
        "INSERT INTO chunk_src(doc_id, sha256) VALUES(?,?) "
        "ON CONFLICT(doc_id) DO UPDATE SET sha256=excluded.sha256",
        (doc_id, src_sha))


def index_doc(conn: sqlite3.Connection, doc_id: str) -> bool:
    """(Re)index ONE document whose txt (and xml, if any) is on disk, keeping
    the FTS index in sync incrementally: the on-demand path, cheap enough
    to run inside a tool call (well under a second for most RFCs). Returns
    False when the document has no local txt."""
    rows = conn.execute(
        """SELECT t.path, t.sha256, x.path AS xml_path, x.sha256 AS xml_sha
           FROM files t LEFT JOIN files x
             ON x.doc_id = t.doc_id AND x.fmt = 'xml'
           WHERE t.fmt = 'txt' AND t.doc_id = ?""", (doc_id,)).fetchall()
    if not rows:
        return False
    r = rows[0]
    mirror = mirror_of(conn)
    path = file_path(conn, r["path"], mirror)
    if not path.exists():
        return False
    xml_path = (file_path(conn, r["xml_path"], mirror) if r["xml_path"]
                else None)
    stats = {"xml_docs": 0, "xml_failed": 0, "txtseg_docs": 0}
    # Take the write lock BEFORE _index_one reads MAX(id) and the old
    # chunks. sqlite3 otherwise opens the transaction at the first INSERT,
    # so two writers (threads of the shared server, or two processes)
    # indexing different documents at once would read the same MAX(id),
    # pick the same new chunk ids, and the second would fail on
    # chunks.id. A waiting writer blocks here for up to busy_timeout.
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _index_one(conn, doc_id, path, _src_sha(r["sha256"], r["xml_sha"]),
                   xml_path, stats, fts_incremental=True)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return True


def build_chunks(conn: sqlite3.Connection, mirror_root: Path,
                 progress=None) -> dict:
    """(Re)chunk every locally-held .txt, incrementally by source hash.

    Documents that also have RFCXML (RFC 8650+) take section boundaries
    from the XML; the source hash then covers txt + xml + parser version, so
    an XML download or a parser fix re-chunks exactly the affected docs.
    """
    rows = conn.execute(
        """SELECT t.doc_id, t.path, t.sha256, x.path AS xml_path,
                  x.sha256 AS xml_sha
           FROM files t LEFT JOIN files x
             ON x.doc_id = t.doc_id AND x.fmt = 'xml'
           WHERE t.fmt = 'txt'""").fetchall()
    stats = {"scanned": len(rows), "rebuilt": 0, "unchanged": 0, "missing": 0,
             "xml_docs": 0, "xml_failed": 0, "txtseg_docs": 0}
    mirror = mirror_of(conn)
    for r in rows:
        path = file_path(conn, r["path"], mirror)
        xml_path = (file_path(conn, r["xml_path"], mirror)
                    if r["xml_path"] else None)
        if not path.exists():
            stats["missing"] += 1
            continue
        src_sha = _src_sha(r["sha256"], r["xml_sha"] if r["xml_path"]
                           else None)
        prev = conn.execute("SELECT sha256 FROM chunk_src WHERE doc_id=?",
                            (r["doc_id"],)).fetchone()
        if prev and prev["sha256"] == src_sha:
            stats["unchanged"] += 1
            continue
        _index_one(conn, r["doc_id"], path, src_sha, xml_path, stats,
                   fts_incremental=False)
        stats["rebuilt"] += 1
        if progress and stats["rebuilt"] % 250 == 0:
            progress(stats["rebuilt"], stats["scanned"])
        if stats["rebuilt"] and stats["rebuilt"] % 1000 == 0:
            conn.commit()
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    from .lexical import backfill_identifiers, mine_acronyms
    stats["idents_backfilled"] = backfill_identifiers(conn)
    if stats["rebuilt"] or not conn.execute(
            "SELECT 1 FROM acronyms LIMIT 1").fetchone():
        stats["acronyms"] = mine_acronyms(conn)
    conn.commit()
    stats["chunks"] = conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
    return stats


def _fts_query(query: str, or_mode: bool = False,
               hybrid_bm25: bool = False,
               extra_phrases: list[str] | None = None) -> str:
    """Pass through expert FTS syntax; fall back to quoted-word AND/OR.

    Pure-numeric tokens are dropped from the default query: the tokenizer
    splits decimals, so "TLS 1.3" would otherwise match every section
    number containing 1.3 (e.g. §4.1.3) in any document. Versioned protocol
    names are still covered by the doc-title ranking list and by embeddings.

    or_mode ranks by number of matched (IDF-weighted) terms instead of
    requiring all of them — the AND conjunct starves recall on real
    questions ("NTP timestamp era rollover" AND-matches 1 chunk in 300k).

    hybrid_bm25 (for RRF candidates) is a two-level OR: bare terms, plus
    the full AND restricted to {sec body} — a chunk whose SECTION TITLE and
    ABSTRACT together carry every term is the canonical passage, and that
    pattern survives porter stemming noise ("era"->"er") and documents that
    merely mention one hot keyword a lot. Porter folds "Reno NewReno" into
    one token; dedup terms for that.
    """
    q = query.strip()
    if re.search(r'"|AND|OR|NEAR|\*|-|\{|\}', q):
        return q
    terms, seen = [], set()
    for t in re.findall(r"[A-Za-z0-9.\-]+", q):
        if re.search(r"[A-Za-z]", t) and t not in seen:
            seen.add(t)
            terms.append(t)
    if not terms:
        terms = re.findall(r"[A-Za-z0-9.\-]+", q)
    if not terms:
        return '""'
    if hybrid_bm25:
        # two-level OR: bare terms for recall; a NEAR proximity group so a
        # chunk carrying ALL terms in one passage outscores term scattered
        # hits. ({col} (...) grouping is not valid FTS5 grammar.)
        parts = [f'"{t}"' for t in terms]
        if 2 <= len(terms) <= 5:
            parts.append("NEAR(" + " ".join(f'"{t}"' for t in terms)
                         + f", {40 * len(terms)})")
        # acronym expansions: "NTP" also matches "network time protocol"
        parts += [f'"{p}"' for p in (extra_phrases or [])]
        return " OR ".join(parts)
    joiner = " OR " if or_mode else " "
    return joiner.join(f'"{t}"' for t in terms)


def search_chunks(conn: sqlite3.Connection, query: str, limit: int = 10,
                  include_obsolete: bool = False,
                  or_mode: bool = False,
                  hybrid_bm25: bool = False,
                  extra_phrases: list[str] | None = None) -> list[dict]:
    sql = """
      SELECT c.id AS chunk_id, c.doc_id, c.sec_num, c.sec_title,
             c.start_line, c.end_line, d.title, d.is_current,
             d.current_status, d.pub_date,
             bm25(chunks_fts, 3.0, 1.0) AS rank,
             snippet(chunks_fts, 1, '>>>', '<<<', ' … ', 16) AS snippet
      FROM chunks_fts
      JOIN chunks c ON c.id = chunks_fts.rowid
      JOIN docs  d ON d.doc_id = c.doc_id
      WHERE chunks_fts MATCH ?"""
    params: list = [_fts_query(query, or_mode=or_mode,
                               hybrid_bm25=hybrid_bm25,
                               extra_phrases=extra_phrases)]
    if not include_obsolete:
        sql += " AND d.is_current = 1"
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        terms = [t for t in re.findall(r"[A-Za-z0-9.\-]+", query)[:8]
                 if re.search(r"[A-Za-z]", t)] or \
                re.findall(r"[A-Za-z0-9.\-]+", query)[:8]
        params[0] = " ".join(f'"{t}"' for t in terms) or '""'
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# section addressing: let a caller ask for "3.4" / "Appendix C" instead of
# doing line arithmetic against a .txt file it should not be reading.

_PART_RE = re.compile(r"\s*\(part \d+/\d+\)$")
_APX_LETTER = re.compile(r"^([A-Z])(?:\.\d+)*$")


def norm_sec(sec: str) -> str:
    """'Section 3.4' | '§3.4' | '3.4.' | 'Appendix C' | 'C' -> the canonical
    sec_num as stored in chunks ('3.4' | 'Appendix C' | '' for unnumbered).

    A bare letter becomes 'Appendix X': the chunker only stores bare letters
    for appendix sub-headings, so 'C' means Appendix C, never section C.
    """
    s = (sec or "").strip().rstrip(".:")
    s = re.sub(r"^(see\s+)?(section|sect|sec|clause|paragraph)\s+", "", s,
               flags=re.I)
    s = s.lstrip("§ ").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(?:appendix|appx)\s*:?\s*([A-Z][a-z]?(?:\.\d+)?)", s,
                     re.I)
    if m:
        lab = m.group(1)[0].upper() + m.group(1)[1:]
        # sub-appendices are stored bare ('Appendix B.1' -> 'B.1')
        return lab if "." in lab else f"Appendix {lab}"
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){0,3}", s):
        return s
    m = re.fullmatch(r"([A-Z][a-z]?)((?:\.\d+)+)", s)
    if m:                                    # 'A.1' stays 'A.1' as stored
        return m.group(1) + m.group(2)
    if re.fullmatch(r"[A-Z][a-z]?", s):
        return f"Appendix {s[0].upper()}"
    return s


def url_frag(sec: str) -> str:
    """rfc-editor.org html anchor for a section number ('' -> no fragment)."""
    if not sec:
        return ""
    if sec.startswith("Appendix"):
        return "appendix-" + sec.split(None, 1)[1]
    if _APX_LETTER.match(sec):
        return "appendix-" + sec
    return "section-" + sec


def section_rows(conn: sqlite3.Connection, doc_id: str, sec: str,
                 deep: bool = True) -> list[dict]:
    """Chunk rows for a section, all parts in order. deep=True also returns
    sub-sections: the chunker stores a parent's own text and its children as
    sibling rows, so the parent row alone is not the whole section."""
    want = norm_sec(sec)
    rows = conn.execute(
        """SELECT id, sec_num, sec_title, start_line, end_line, sha256
           FROM chunks WHERE doc_id = ? ORDER BY start_line, id""",
        (doc_id,)).fetchall()
    out: list[dict] = []
    for r in rows:
        sn = r["sec_num"]
        if sn == want:
            out.append(dict(r))
        elif deep and want and sn.startswith(want + "."):
            out.append(dict(r))
        elif deep and want and want.startswith("Appendix ") and \
                _APX_LETTER.match(sn or "") and \
                sn[0] == want.split(None, 1)[1][0]:
            out.append(dict(r))     # 'Appendix C' owns its 'C.1' sub-headings
    return out


def get_toc(conn: sqlite3.Connection, doc_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT sec_num, sec_title, start_line, end_line,
                  substr(replace(body, char(10), ' '), 1, 90) AS preview
           FROM chunks WHERE doc_id = ?
           ORDER BY start_line, id""", (doc_id,)).fetchall()
    return [dict(r) for r in rows]


def resolve_span(conn: sqlite3.Connection, doc_id: str, sec: str) -> dict:
    """Resolve a section reference to a line span, or explain why it failed.

    ok=False carries 'suggestions' (nearest section numbers) plus the real
    outline: the usual cause is a number borrowed from another document or
    dropped by a rename, and guessing is worse than showing the outline.
    """
    import difflib
    want = norm_sec(sec)
    rows = section_rows(conn, doc_id, want)
    if rows:
        title = _PART_RE.sub("", rows[0]["sec_title"] or "")
        start = min(r["start_line"] for r in rows)
        end = max(r["end_line"] for r in rows)
        # RFCXML heading row: the section's own title and heading line even
        # when it has no text of its own (rows[0] is then its first child).
        head = conn.execute(
            "SELECT sec_title, start_line, end_line FROM blocks WHERE "
            "doc_id=? AND kind='heading' AND sec_num=?", (doc_id, want)
        ).fetchone() if want else None
        if head:
            title = head["sec_title"]
            start = min(start, head["start_line"])
            end = max(end, head["end_line"])
        return {"ok": True, "sec_num": want, "sec_title": title,
                "start_line": start, "end_line": end,
                "subsections": sorted({r["sec_num"] for r in rows
                                       if r["sec_num"] != want}),
                "url_frag": url_frag(want), "parts": len(rows)}
    known = conn.execute(
        "SELECT DISTINCT sec_num, sec_title FROM chunks WHERE doc_id=?",
        (doc_id,)).fetchall()
    if not known:
        return {"ok": False, "sec_num": want, "indexed": False,
                "reason": f"{doc_id} is not section-indexed "
                          "(run `rfclib index build`)"}
    names = [k["sec_num"] for k in known if k["sec_num"]]
    near = difflib.get_close_matches(want, names, n=4, cutoff=0.5)
    if not near:  # numbers wrong but the title right is common
        low = (sec or "").strip().lower()
        near = [k["sec_num"] for k in known
                if low and low in (k["sec_title"] or "").lower()][:4]
    return {"ok": False, "sec_num": want, "indexed": True,
            "reason": f"no section {want or '(unnumbered)'} in {doc_id}",
            "suggestions": near,
            "outline": [f"{k['sec_num']} {k['sec_title']}".strip()
                        for k in known if k["sec_num"]][:40]}


def toc(conn: sqlite3.Connection, doc_id: str, depth: int | None = None,
        collapse_parts: bool = True, contains: str | None = None,
        preview: bool = False) -> list[dict]:
    """Section outline with one row per real section (chunk parts merged), so
    a 70-section RFC costs 70 rows instead of 120 `(part 3/21)` artifacts.

    depth: keep sections with at most this many dot-levels ('7.2' -> 2).
    contains: substring filter on section number or title.
    """
    rows = conn.execute(
        """SELECT sec_num, sec_title, start_line, end_line,
                  substr(replace(body, char(10), ' '), 1, 90) AS preview
           FROM chunks WHERE doc_id = ? ORDER BY start_line, id""",
        (doc_id,)).fetchall()
    merged: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        title = _PART_RE.sub("", r["sec_title"] or "")
        key = f"{r['sec_num']}\x00{title}"
        m = merged.get(key)
        if m is None:
            m = merged[key] = {"sec_num": r["sec_num"], "title": title,
                               "start_line": r["start_line"],
                               "end_line": r["end_line"], "parts": 1,
                               "preview": r["preview"]}
            order.append(key)
        elif collapse_parts:
            m["start_line"] = min(m["start_line"], r["start_line"])
            m["end_line"] = max(m["end_line"], r["end_line"])
            m["parts"] += 1
        else:
            key2 = f"{key}\x01{len(order)}"
            merged[key2] = dict(m, parts=1, preview=r["preview"])
            order.append(key2)
    # RFCXML docs: a section with no text of its own ('1. Introduction'
    # holding only 1.1-1.4) has no chunk; its heading row fills the gap
    # (parts=0: read it with section='1' to get the subsections).
    have = {m["sec_num"] for m in merged.values()}
    for h in conn.execute(
            "SELECT sec_num, sec_title, start_line, end_line FROM blocks "
            "WHERE doc_id=? AND kind='heading' AND sec_num<>''", (doc_id,)):
        if h["sec_num"] in have:
            continue
        key = f"{h['sec_num']}\x00{h['sec_title']}"
        merged[key] = {"sec_num": h["sec_num"], "title": h["sec_title"],
                       "start_line": h["start_line"],
                       "end_line": h["end_line"], "parts": 0,
                       "preview": ""}
        order.append(key)
    order.sort(key=lambda k: merged[k]["start_line"])
    out = []
    for k in order:
        s = merged[k]
        if depth is not None and s["sec_num"].count(".") + 1 > depth:
            continue
        if contains:
            needle = contains.lower()
            if needle not in s["sec_num"].lower() and \
                    needle not in (s["title"] or "").lower():
                continue
        if not preview:
            s.pop("preview", None)
        out.append(s)
    return out


def index_stats(conn: sqlite3.Connection) -> dict:
    return {
        "chunked_docs": conn.execute(
            "SELECT COUNT(*) c FROM chunk_src").fetchone()["c"],
        "chunks": conn.execute(
            "SELECT COUNT(*) c FROM chunks").fetchone()["c"],
        "embedded_chunks": conn.execute(
            "SELECT COUNT(*) c FROM embed_state").fetchone()["c"],
    }