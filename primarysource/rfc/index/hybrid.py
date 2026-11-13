"""Hybrid retrieval: RRF fusion of BM25 + KNN + doc-title matches, status-aware.

RRF (score = sum of 1/(k+rank) per list, k=60) is rank-based, so it needs
no score calibration between bm25 and cosine distance. On top, a small
multiplicative prior favors standards-track and BCP/STD documents — for
normative questions an Internet Standard outranks an Experimental memo
that happens to mention the same words.
"""

from __future__ import annotations

import math
import re
import sqlite3

# k=25 (not the classic 60): our lists are shallow (depth ~30) and we want
# a #2 BM25 hit to actually move its document, not drown in flat 1/(60+r).
RRF_K = 25

# multiplicative prior on current_status (from the rfc-index manifest)
_STATUS_PRIOR = (
    ("INTERNET STANDARD", 1.25),
    ("BEST CURRENT PRACTICE", 1.20),
    ("DRAFT STANDARD", 1.15),
    ("PROPOSED STANDARD", 1.10),
    ("HISTORIC", 0.80),
)

# weight of the document title/abstract match in the RRF sum, proportional
# to IDF-weighted term COVERAGE: "Key words for use in RFCs..." (coverage
# 2.3, RFC2119's literal title) must lift its doc ~2.3x as hard as a doc
# whose title carries one weak term. Capped so one title can't outrank a
# doc backed by two strong lists unconditionally.
TITLE_BOOST_BASE, TITLE_BOOST_COV, TITLE_BOOST_CAP = 0.15, 0.7, 1.4

# weight of the exact-identifier list (lexical.ident_search) relative to the
# BM25 and KNN lists (1.0 each); only present when the query has identifiers
# (0.5: at 1.0 a frequent identifier such as base64url pushed the defining
# RFC out of the top 5; at 0.5 identifier MRR rises 0.556 -> 0.631 with no
# top-5 losses on scripts/eval_retrieval.py)
IDENT_WEIGHT = 0.5


def status_prior(current_status: str | None, is_current: bool = True) -> float:
    st = (current_status or "").upper()
    for needle, w in _STATUS_PRIOR:
        if needle in st:
            return w if is_current else min(w, 0.8)
    return 1.0


def _has(text: str, word: str, alts: dict[str, str]) -> bool:
    """word occurs in text, or word is a query acronym whose expansion does."""
    if re.search(rf"\b{re.escape(word)}\b", text):
        return True
    exp = alts.get(word)
    return bool(exp) and re.search(rf"\b{re.escape(exp)}\b", text) is not None


def _doc_title_list(conn: sqlite3.Connection, query: str,
                    include_obsolete: bool,
                    alts: dict[str, str] | None = None) -> list[dict]:
    """Document-level (title/abstract) matches ranked by TERM COVERAGE.

    Raw bm25 over an OR of terms lets one rare word ("NewReno", "QUIC")
    win the list; what identifies the canonical spec is the FRACTION of
    query terms the document's own title/abstract carries ("TCP
    Congestion Control" ⊃ "congestion control TCP Reno NewReno"). So:
    bm25 pulls a wide candidate pool, then IDF-weighted coverage reorders
    it. AND conjuncts would drop docs missing one incidental word.

    alts maps a query acronym to its expansion: "ntp" is covered by a title
    that says "Network Time Protocol" (RFC 5905 never says "NTP").
    """
    alts = alts or {}
    words, seen = [], set()
    # keep decimal version tokens ("1.3", "2.0", "802.11"): they are often
    # THE discriminator — "TLS 1.3 handshake" must beat generic TLS docs.
    for t in re.findall(r"[A-Za-z0-9]+(?:\.[0-9]+)*", query):
        if (re.search(r"[A-Za-z]", t) or "." in t) and t.lower() not in seen:
            seen.add(t.lower())
            words.append(t.lower())
    if not words:
        return []
    sql = ("SELECT d.doc_id, bm25(docs_fts) AS rank FROM docs_fts "
           "JOIN docs d ON d.doc_id = docs_fts.doc_id "
           "WHERE docs_fts MATCH ?")
    params: list = [" OR ".join([f'"{w}"' for w in words]
                                + [f'"{e}"' for e in alts.values()])]
    if not include_obsolete:
        sql += " AND d.is_current = 1"
    sql += " ORDER BY rank LIMIT 300"
    try:
        cand = [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.OperationalError:
        return []
    # long specs have diluted bm25 and can miss a 300-row pool, yet their
    # TITLE may be the exact answer — sweep titles directly (docs is ~10k
    # rows, LIKE is negligible) and merge them into the candidate set.
    have = {c["doc_id"] for c in cand}
    for w in words + list(alts.values()):
        wsql = ("SELECT doc_id, 1000 AS rank FROM docs "
                "WHERE lower(title) LIKE ?")
        if not include_obsolete:
            wsql += " AND is_current = 1"
        for r in conn.execute(wsql, (f"%{w}%",)).fetchall():
            if r[0] not in have:
                have.add(r[0])
                cand.append({"doc_id": r[0], "rank": r[1]})

    total = max(conn.execute("SELECT COUNT(*) FROM docs_fts").fetchone()[0],
                1)
    weights = {}
    for w in words:
        try:
            df = conn.execute(
                "SELECT COUNT(*) FROM docs_fts WHERE docs_fts MATCH ?",
                (f'"{w}"',)).fetchone()[0]
        except sqlite3.OperationalError:
            df = 1
        weights[w] = max(0.0, math.log(total / max(df, 1)))
    wsum = sum(weights.values()) or 1.0

    scored = []
    for c in cand:
        row = conn.execute(
            "SELECT lower(COALESCE(title,'')) t, lower(COALESCE(title,'') "
            "|| ' ' || COALESCE(abstract,'') || ' ' || "
            "COALESCE(keywords,'')) a FROM docs WHERE doc_id=?",
            (c["doc_id"],)).fetchone()
        title = row["t"] if row else ""
        full = row["a"] if row else ""
        hit_t = sum(weights[w] for w in words if _has(title, w, alts)) / wsum
        hit_a = sum(weights[w] for w in words if _has(full, w, alts)) / wsum
        # THE TITLE IS THE DOCUMENT'S IDENTITY: a spec whose title carries
        # the query terms outscores one whose long abstract merely
        # mentions them (surveys lose to RFC9000 for "QUIC transport").
        scored.append((2.0 * hit_t + 0.3 * hit_a, c))
    scored.sort(key=lambda x: (-x[0], x[1]["rank"]))
    out = []
    for cov, c in scored[:25]:
        if cov <= 0.15:
            break
        c["coverage"] = round(cov, 3)
        out.append(c)
    return out


def hybrid_search(conn: sqlite3.Connection, query: str, limit: int = 10,
                  include_obsolete: bool = False,
                  depth: int = 0) -> list[dict]:
    """Fuse section BM25, embedding KNN and doc-title lists via weighted RRF."""
    from . import embed as ix_embed
    from . import lexical
    from . import search as ix_search

    depth = depth or max(5 * limit, 100)
    alts = lexical.expansions(conn, query)          # {'ntp': 'network ...'}
    # acronym expansions stay out of the BM25 query: "border gateway
    # protocol" pulls in every BGP document; they only count toward title
    # coverage, where a title spells the acronym out (RFC 5905's)
    bm25 = ix_search.search_chunks(conn, query, limit=depth,
                                   include_obsolete=include_obsolete,
                                   hybrid_bm25=True)
    try:
        # (acronym expansions are NOT appended here: measured on the golden
        # set, the gains came from wrong expansions and were offset by
        # losses on TLS, TCP, PKCS and BGP queries)
        knn = ix_embed.semantic_search(conn, query, limit=depth,
                                       include_obsolete=include_obsolete)
    except RuntimeError:
        knn = []  # vectors not built yet: degrade to pure BM25
    # exact identifier matches (preferred_address, X25519, Content-Length):
    # its own list, so the section that contains THE identifier is not
    # outvoted by sections that merely share its words
    ident = lexical.ident_search(conn, query, depth, include_obsolete)
    ident_w = (IDENT_WEIGHT * lexical.ident_weight(conn, query) if ident
               else 0.0)

    doc_hits = _doc_title_list(conn, query, include_obsolete, alts)
    doc_rank = {h["doc_id"]: r for r, h in enumerate(doc_hits)}

    # diversify each input list BEFORE fusing: three chunks of one hot RFC
    # should not occupy ranks 1-3 and push the canonical spec out of reach
    def _once_per_doc(lst: list[dict]) -> list[dict]:
        seen, out = set(), []
        for h in lst:
            if h["doc_id"] not in seen:
                seen.add(h["doc_id"])
                out.append(h)
        return out

    bm25 = _once_per_doc(bm25)
    knn = _once_per_doc(knn)
    ident = _once_per_doc(ident)

    fused: dict[int, dict] = {}
    for rank, h in enumerate(bm25):
        e = fused.setdefault(h["chunk_id"], {
            "chunk_id": h["chunk_id"], "doc_id": h["doc_id"],
            "sec_num": h["sec_num"], "sec_title": h["sec_title"],
            "start_line": h["start_line"], "end_line": h["end_line"],
            "title": h["title"], "is_current": h["is_current"],
            "current_status": h.get("current_status"),
            "snippet": h["snippet"], "rrf": 0.0, "bm25_rank": None,
            "knn_rank": None})
        e["rrf"] += 1.0 / (RRF_K + rank + 1)
        e["bm25_rank"] = rank + 1
    for rank, h in enumerate(knn):
        e = fused.get(h["chunk_id"])
        if e is None:
            e = fused[h["chunk_id"]] = {
                "chunk_id": h["chunk_id"], "doc_id": h["doc_id"],
                "sec_num": h["sec_num"], "sec_title": h["sec_title"],
                "start_line": h["start_line"], "end_line": h["end_line"],
                "title": h["title"], "is_current": h["is_current"],
                "current_status": h.get("current_status"),
                "snippet": h["preview"][:240], "rrf": 0.0,
                "bm25_rank": None, "knn_rank": None}
        e["rrf"] += 1.0 / (RRF_K + rank + 1)
        e["knn_rank"] = rank + 1
    for rank, h in enumerate(ident):
        e = fused.get(h["chunk_id"])
        if e is None:
            e = fused[h["chunk_id"]] = {
                "chunk_id": h["chunk_id"], "doc_id": h["doc_id"],
                "sec_num": h["sec_num"], "sec_title": h["sec_title"],
                "start_line": h["start_line"], "end_line": h["end_line"],
                "title": h["title"], "is_current": h["is_current"],
                "current_status": h.get("current_status"),
                "snippet": h["preview"][:240], "rrf": 0.0,
                "bm25_rank": None, "knn_rank": None}
        e["rrf"] += ident_w / (RRF_K + rank + 1)
        e["ident_rank"] = rank + 1

    # a title-matching doc with no chunk in either section list is exactly
    # the "find me the TLS 1.3 spec" case: surface its Abstract section as
    # a rank-`dr` entry of the title list (the final loop adds the boost)
    for dr, dh in enumerate(doc_hits[:5]):
        if any(e["doc_id"] == dh["doc_id"] for e in fused.values()):
            continue
        rep = conn.execute(
            """SELECT c.id AS chunk_id, c.doc_id, c.sec_num, c.sec_title,
                      c.start_line, c.end_line, d.title, d.is_current,
                      d.current_status,
                      substr(replace(c.body, char(10), ' '), 1, 240) AS preview
               FROM chunks c JOIN docs d ON d.doc_id = c.doc_id
               WHERE c.doc_id = ?
               ORDER BY (c.sec_title = 'Abstract') DESC, c.start_line
               LIMIT 1""", (dh["doc_id"],)).fetchone()
        if rep is None:
            continue
        fused[rep["chunk_id"]] = {
            "chunk_id": rep["chunk_id"], "doc_id": rep["doc_id"],
            "sec_num": rep["sec_num"], "sec_title": rep["sec_title"],
            "start_line": rep["start_line"], "end_line": rep["end_line"],
            "title": rep["title"], "is_current": rep["is_current"],
            "current_status": rep["current_status"],
            "snippet": rep["preview"], "rrf": 1.0 / (RRF_K + dr + 1),
            "bm25_rank": None, "knn_rank": None}

    # doc-level corroboration: fusion is chunk-keyed, so BM25 hitting §6
    # and KNN hitting §3 of the SAME doc never sum (RFC5905 for "NTP era
    # rollover" died exactly this way). The doc's best chunk absorbs a
    # share of its siblings' rrf before the title boost is applied.
    best_by_doc: dict[str, dict] = {}
    for e in fused.values():
        cur = best_by_doc.get(e["doc_id"])
        if cur is None or e["rrf"] > cur["rrf"]:
            best_by_doc[e["doc_id"]] = e
    for e in fused.values():
        b = best_by_doc[e["doc_id"]]
        if b is not e:
            b["rrf"] += 0.5 * e["rrf"]

    for e in fused.values():
        p = status_prior(e["current_status"], bool(e["is_current"]))
        if ix_search.NOISE_TITLE_RE.search(e["sec_title"] or ""):
            p *= 0.55
        e["rrf"] *= p
        dr = doc_rank.get(e["doc_id"])
        if dr is not None and dr < 15:  # chunk of a doc whose title matched
            cov = min(doc_hits[dr]["coverage"], TITLE_BOOST_CAP)
            e["rrf"] += (TITLE_BOOST_BASE + TITLE_BOOST_COV * cov) \
                / (RRF_K + dr + 1)
        e["sources"] = "+".join(
            n for n, hit in (("bm25", e["bm25_rank"]), ("knn", e["knn_rank"]),
                             ("ident", e.get("ident_rank")), ("title", dr))
            if hit is not None)
        e["rrf"] = round(e["rrf"], 5)
    # diversify: the best chunk of each document first, then overflow —
    # ten hits on six chunks of one RFC teach the agent nothing new
    ordered = sorted(fused.values(), key=lambda e: -e["rrf"])
    seen: set[str] = set()
    ranked, overflow = [], []
    for e in ordered:
        if e["doc_id"] in seen:
            overflow.append(e)
        else:
            seen.add(e["doc_id"])
            ranked.append(e)
    ranked = (ranked + overflow)[:limit]
    for e in ranked:
        e.pop("preview", None)
    return ranked