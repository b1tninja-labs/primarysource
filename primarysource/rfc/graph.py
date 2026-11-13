"""Cross-reference graph mined from the local RFC .txt corpus.

RFCs cite each other with bracketed tags ([RFC9000]) inside numbered
References sections (normative vs informative by subsection), and point
at specific sections with "Section 7.4.1 of [RFC9110]" / "[RFC9110],
Section 4.2" phrasing. Mining those patterns from text we already
store yields the full document-level citation graph plus section-level
anchors, with zero extra downloads (no XML mirror needed).

Build is incremental: ref_src keeps each source txt's sha256 so
re-running only re-mines changed documents.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .sync.downloader import sha256_file
from .sync.state import file_path, mirror_of

_SERIES = r"(?:RFC|BCP|STD|FYI)"

# [RFC9000], [BCP 14], [STD 1] ... (spaced or not)
_REF_TAG = re.compile(rf"\[({_SERIES})\s?(\d{{1,5}})\]")

# Body header of the references area, e.g. "19.  References",
# "     19.1.  Normative References". TOC lines are excluded because
# they end with dot-leaders + page number, not with "References".
_HDR_REF = re.compile(
    r"^\s*(\d+(?:\.\d+)*)?\.?\s{1,3}(Normative|Informative)?\s*"
    r"References:?\s*$")

# Any numbered body header (used to leave the references area).
_HDR_NUM = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s{1,3}[A-Z]")

# Section-anchored citations, the common phrasings:
#   "Section 7.4.1 of [RFC9110]"        "Sections 4.1 ... of RFC 9001"
#   "[RFC9110], Section 4.2"            "[RFC9110] Section 4.2"
#   "RFC 9001, Section 5.4"             "Appendix C of [RFC6962]"
_SEC_OF = re.compile(
    rf"\b[Ss]ections?\s+((?:\d+|[A-Z])[\w.\-]{{0,12}})\s+of\s+\[?\s*"
    rf"({_SERIES})\s?(\d{{1,5}})\s*\]?")
_SEC_TAG = re.compile(
    rf"\[({_SERIES})\s?(\d{{1,5}})\](?:,|\s+)?[Ss]ections?\s+"
    r"((?:\d+|[A-Z])[\w.\-]{0,12})")
_SEC_PLAIN = re.compile(
    rf"\b({_SERIES})\s?(\d{{1,5}})\s*[,\u2014]+\s+[Ss]ections?\s+"
    r"((?:\d+|[A-Z])[\w.\-]{0,12})")
_SEC_APPX = re.compile(
    rf"\bAppendix\s+([A-Z](?:\.\d+)?)\s+of\s+\[?\s*({_SERIES})\s?"
    r"(\d{1,5})\s*\]?")


def _clean_sec(sec: str) -> str:
    return sec.strip().rstrip(".,:;")[:16]


def extract_refs(text: str, known: set[str]) -> list[tuple[str, str, str]]:
    """Mine (dst, kind, sec) edges from one RFC's txt.

    kind is normative|informative|reference for tags inside the
    References section, mention for section-anchored citations found
    anywhere in the document. dst is only emitted when the target id
    exists in `known`.
    """
    edges: set[tuple[str, str, str]] = set()
    zone: str | None = None         # None|reference|normative|informative
    zone_prefix: str | None = None  # e.g. '19' while inside section 19(.x)

    for line in text.splitlines():
        m = _HDR_REF.match(line)
        if m:
            num, sub = m.group(1), m.group(2)
            zone = ("normative" if sub == "Normative" else
                    "informative" if sub == "Informative" else "reference")
            zone_prefix = num
            continue
        h = _HDR_NUM.match(line)
        if h and zone is not None:
            num = h.group(1)
            if not (zone_prefix and (num == zone_prefix
                                     or num.startswith(zone_prefix + "."))):
                zone = None         # left the references section
            continue

        # TOC lines (dot leaders) mirror headings + can contain tags;
        # they never carry real citations, skip them entirely.
        if ". ." in line:
            continue

        if zone is not None:
            for series, num in _REF_TAG.findall(line):
                dst = series + num
                if dst in known:
                    edges.add((dst, zone, ""))

        for sec, series, num in _SEC_OF.findall(line):
            dst = series + num
            if dst in known:
                edges.add((dst, "mention", _clean_sec(sec)))
        for sec, series, num in _SEC_APPX.findall(line):
            dst = series + num
            if dst in known:
                edges.add((dst, "mention", _clean_sec(sec)))
        for series, num, sec in _SEC_TAG.findall(line):
            dst = series + num
            if dst in known:
                edges.add((dst, "mention", _clean_sec(sec)))
        for series, num, sec in _SEC_PLAIN.findall(line):
            dst = series + num
            if dst in known:
                edges.add((dst, "mention", _clean_sec(sec)))

    return sorted(edges)


def build(conn: sqlite3.Connection, doc_ids: list[str] | None = None,
          force: bool = False, progress=None) -> dict:
    """(Re-)mine ref edges for docs with a local txt; sha-incremental."""
    known = {r[0] for r in conn.execute("SELECT doc_id FROM docs")}
    src_sha = {r["doc_id"]: r["sha256"] for r in
               conn.execute("SELECT doc_id, sha256 FROM ref_src")}
    rows = conn.execute("SELECT doc_id, path FROM files WHERE fmt='txt'")\
             .fetchall()
    if doc_ids:
        want = set(doc_ids)
        rows = [r for r in rows if r["doc_id"] in want]
    built = skipped = total_edges = 0
    mirror = mirror_of(conn)
    for i, r in enumerate(rows, 1):
        path = file_path(conn, r["path"], mirror)
        if not path.is_file():
            continue
        sha = sha256_file(path)
        if not force and src_sha.get(r["doc_id"]) == sha:
            skipped += 1
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        edges = extract_refs(text, known)
        conn.execute("DELETE FROM ref_edges WHERE src=?", (r["doc_id"],))
        conn.executemany(
            "INSERT OR IGNORE INTO ref_edges(src,dst,kind,sec) VALUES(?,?,?,?)",
            [(r["doc_id"], d, k, s) for d, k, s in edges])
        conn.execute(
            "INSERT INTO ref_src(doc_id,sha256) VALUES(?,?) "
            "ON CONFLICT(doc_id) DO UPDATE SET sha256=excluded.sha256",
            (r["doc_id"], sha))
        built += 1
        total_edges += len(edges)
        if progress:
            progress(i, len(rows), r["doc_id"], len(edges))
        if i % 250 == 0:
            conn.commit()
    conn.commit()
    return {"built": built, "skipped_unchanged": skipped,
            "new_edges": total_edges,
            "total_edges": conn.execute(
                "SELECT COUNT(*) FROM ref_edges").fetchone()[0]}


_RANK = {"normative": 0, "informative": 1, "reference": 2, "mention": 3}


def _num(doc_id: str) -> int:
    m = re.match(r"\D*(\d+)", doc_id)
    return int(m.group(1)) if m else 0


def _sec_key(s: str):
    return [int(p) if p.isdigit() else p
            for p in re.split(r"[.\-]", s)]


def get_refs(conn: sqlite3.Connection, doc_id: str,
             limit: int = 100) -> dict:
    """Merged citation view: outbound (this doc cites) and inbound."""
    def side(col_own: str, col_peer: str) -> tuple[list[dict], int]:
        agg: dict[str, dict] = {}
        for r in conn.execute(
                f"SELECT {col_peer} peer, kind, sec FROM ref_edges "
                f"WHERE {col_own}=?", (doc_id,)):
            e = agg.setdefault(r["peer"], {"doc_id": r["peer"],
                                           "kinds": set(), "sections": set()})
            e["kinds"].add(r["kind"])
            if r["sec"]:
                e["sections"].add(r["sec"])
        titles = {}
        if agg:
            titles = {t["doc_id"]: (t["title"], bool(t["is_current"]))
                      for t in conn.execute(
                          "SELECT doc_id, title, is_current FROM docs "
                          "WHERE doc_id IN (%s)"
                          % ",".join("?" * len(agg)), list(agg))}
        out = []
        for peer, e in agg.items():
            title, current = titles.get(peer, (None, True))
            kinds = sorted(e["kinds"], key=lambda k: _RANK.get(k, 9))
            out.append({"doc_id": peer, "title": title,
                        "is_current": current, "kinds": kinds,
                        "sections": sorted(e["sections"], key=_sec_key)[:12]})
        out.sort(key=lambda x: (_RANK.get(x["kinds"][0], 9),
                                -_num(x["doc_id"])))
        return out[:limit], len(out)

    outbound, n_out = side("src", "dst")
    inbound, n_in = side("dst", "src")
    return {"doc_id": doc_id,
            "outbound": outbound, "outbound_count": n_out,
            "inbound": inbound, "inbound_count": n_in,
            "built": conn.execute(
                "SELECT COUNT(*) FROM ref_src").fetchone()[0] > 0}