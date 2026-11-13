"""Lexical helpers for searching protocol text: identifiers and acronyms.

The section index (chunks_fts) uses `porter unicode61`, which is right for
prose but splits the tokens RFC readers search for most precisely:
"preferred_address" becomes "preferr" + "address", "Sec-WebSocket-Accept"
three words, "X25519" stays whole but "KeyUpdate" loses its identity once
stemmed. Two small additions keep the main index and repair the rest:

ident_fts   one row per section holding only its identifier-shaped tokens
            (snake_case, SCREAMING_CASE, hyphenated names, CamelCase, mixed
            letters+digits), tokenized with '_' and '-' kept inside tokens.
            A query carrying such tokens gets an extra ranked list in hybrid
            fusion: sections that contain THE identifier, not its words.

acronyms    "Network Time Protocol (NTP)" pairs mined from the corpus, kept
            only when the acronym's letters are the initials of the words.
            A query acronym is then also covered by a title that spells it
            out (RFC 5905's title never says "NTP").

Query stop words were tried and measured worse (topic MRR 0.694 -> 0.653
on scripts/eval_retrieval.py): BM25's IDF already discounts them, and
dropping them broke title matches like RFC 2119's "Key words for use in
RFCs ...". So there are none.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict

_IDENT = re.compile(r"""
      [A-Za-z0-9]+(?:_[A-Za-z0-9]+)+          # snake_case, SCREAMING_SNAKE
    | [A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+  # Content-Length, SYN-RECEIVED
    | [A-Za-z]+[0-9][A-Za-z0-9]*              # X25519, SHA256, UUIDv7, IPv6
    | [A-Z][a-z]+[A-Z][A-Za-z0-9]*            # KeyUpdate, NewReno, WebSocket
    | [a-z]+[A-Z][A-Za-z0-9]*                 # camelCase
""", re.X)
_NOT_IDENT = re.compile(r"^(rfc|bcp|std|fyi)\d+$|^[a-z]+-$", re.I)


def identifiers(text: str) -> list[str]:
    """Identifier-shaped tokens of text, lowercased, in order (with repeats:
    term frequency still means something). RFC numbers are left out: they
    are citations, served by the citation graph."""
    out = []
    for m in _IDENT.finditer(text):
        t = m.group(0).strip("-_").lower()
        if len(t) >= 3 and not _NOT_IDENT.match(t):
            out.append(t)
    return out


# --------------------------------------------------------------------------
# identifier index

def index_identifiers(conn: sqlite3.Connection, chunk_ids: list[int],
                      drop_ids: list[int] = ()) -> None:
    """(Re)write ident_fts rows for these chunks; drop rows of chunks that
    no longer exist."""
    if drop_ids:
        conn.executemany("DELETE FROM ident_fts WHERE rowid=?",
                         [(i,) for i in drop_ids])
    for cid in chunk_ids:
        row = conn.execute("SELECT body FROM chunks WHERE id=?",
                           (cid,)).fetchone()
        conn.execute("DELETE FROM ident_fts WHERE rowid=?", (cid,))
        terms = identifiers(row[0]) if row else []
        if terms:
            conn.execute("INSERT INTO ident_fts(rowid, terms) VALUES(?,?)",
                         (cid, " ".join(terms)))


def backfill_identifiers(conn: sqlite3.Connection, progress=None) -> int:
    """Index sections that have no ident_fts row yet (after an upgrade)."""
    todo = [r[0] for r in conn.execute(
        "SELECT id FROM chunks WHERE id NOT IN (SELECT rowid FROM ident_fts)"
        " AND id NOT IN (SELECT chunk_id FROM ident_none)")]
    for i in range(0, len(todo), 2000):
        part = todo[i:i + 2000]
        for cid, body in conn.execute(
                "SELECT id, body FROM chunks WHERE id IN (%s)"
                % ",".join("?" * len(part)), part).fetchall():
            terms = identifiers(body)
            if terms:
                conn.execute("INSERT INTO ident_fts(rowid, terms) "
                             "VALUES(?,?)", (cid, " ".join(terms)))
            else:   # remember "nothing to index" so backfill stays cheap
                conn.execute("INSERT OR IGNORE INTO ident_none(chunk_id) "
                             "VALUES(?)", (cid,))
        conn.commit()
        if progress:
            progress(min(i + 2000, len(todo)), len(todo))
    return len(todo)


def ident_weight(conn: sqlite3.Connection, query: str) -> float:
    """How much an exact-identifier match should count, 0..1: by the
    rarest identifier's document frequency. 'preferred_address' (1 RFC)
    pins its section; 'base64url' (78 RFCs) or 'Content-Length' (278) says
    little about which RFC is meant, and must not outvote the other lists."""
    import math
    terms = list(dict.fromkeys(identifiers(query)))
    if not terms:
        return 0.0
    total = max(conn.execute("SELECT COUNT(*) FROM chunk_src").fetchone()[0],
                2)
    best = 0.0
    for t in terms:
        try:
            df = conn.execute(
                "SELECT COUNT(DISTINCT c.doc_id) FROM ident_fts JOIN chunks c "
                "ON c.id = ident_fts.rowid WHERE ident_fts MATCH ?",
                (f'"{t}"',)).fetchone()[0]
        except sqlite3.OperationalError:
            continue
        if df:
            best = max(best, math.log(total / df) / math.log(total))
    return best ** 2       # sharpen: rare -> ~1, common -> small


def ident_search(conn: sqlite3.Connection, query: str, limit: int,
                 include_obsolete: bool = False) -> list[dict]:
    """Sections ranked by BM25 over the query's identifier tokens only;
    [] when the query has none."""
    terms = list(dict.fromkeys(identifiers(query)))
    if not terms:
        return []
    sql = """
      SELECT c.id AS chunk_id, c.doc_id, c.sec_num, c.sec_title,
             c.start_line, c.end_line, d.title, d.is_current,
             d.current_status,
             substr(replace(c.body, char(10), ' '), 1, 240) AS preview
      FROM ident_fts JOIN chunks c ON c.id = ident_fts.rowid
      JOIN docs d ON d.doc_id = c.doc_id
      WHERE ident_fts MATCH ?"""
    if not include_obsolete:
        sql += " AND d.is_current = 1"
    sql += " ORDER BY bm25(ident_fts) LIMIT ?"
    match = " OR ".join(f'"{t}"' for t in terms)
    try:
        return [dict(r) for r in conn.execute(sql, (match, limit))]
    except sqlite3.OperationalError:
        return []


# --------------------------------------------------------------------------
# acronyms

_EXPANSION = re.compile(
    r"((?:[A-Za-z][\w/]*[\s-]+){1,8}?[A-Za-z][\w/]*)\s+\(([A-Z][A-Za-z0-9]{1,9})s?\)")
_JOIN = {"of", "for", "and", "the", "to", "over", "in", "on", "a", "an", "with"}


def _match_initials(acro: str, words: list[str]) -> list[str] | None:
    """The shortest suffix of words whose initials spell acro's letters
    (join words may be skipped, a word may contribute 2 letters as in
    'IPsec' / 'Ethernet' cases are left out). None if no suffix fits."""
    letters = [ch.lower() for ch in acro if ch.isalpha()]
    if len(letters) < 2:
        return None
    for start in range(len(words) - 1, -1, -1):
        cand = words[start:]
        initials = [w[0].lower() for w in cand
                    if w.lower() not in _JOIN or w[0].isupper()]
        if initials == letters:
            if cand[0].lower() in _JOIN:
                return None
            return cand
        if len(initials) > len(letters):
            break
    return None


def mine_acronyms(conn: sqlite3.Connection) -> int:
    """Rebuild the acronyms table from titles, abstracts, keywords and the
    opening sections of every indexed document (where terms are defined)."""
    counts: dict[str, Counter] = defaultdict(Counter)

    def scan(text: str) -> None:
        for m in _EXPANSION.finditer(text or ""):
            acro = m.group(2)
            words = re.split(r"[\s-]+", m.group(1).strip())
            hit = _match_initials(acro, words)
            if hit:
                counts[acro.upper()][" ".join(w.lower() for w in hit)] += 1

    for r in conn.execute("SELECT title, abstract, keywords FROM docs"):
        scan(" ".join(x or "" for x in r))
    for (body,) in conn.execute(
            "SELECT body FROM chunks WHERE sec_title IN ('Abstract', "
            "'Introduction', 'Terminology', 'Overview') OR sec_num IN "
            "('1', '1.1', '2')"):
        scan(body.replace("\n", " "))
    conn.execute("DELETE FROM acronyms")
    rows = []
    for acro, exp in counts.items():
        expansion, n = exp.most_common(1)[0]
        # one sighting is noise ('QUIC' is not an acronym); series names
        # are document ids, not terms to expand
        if n >= 2 and acro not in ("RFC", "RFCS", "BCP", "STD", "FYI"):
            rows.append((acro, expansion, n))
    conn.executemany("INSERT INTO acronyms(acro, expansion, n) "
                     "VALUES(?,?,?)", rows)
    conn.commit()
    return len(rows)


def expansions(conn: sqlite3.Connection, query: str) -> dict[str, str]:
    """{query acronym (lowercase): expansion} for acronyms the query uses
    in capitals ('NTP', 'DCCP'); an all-lowercase query word is left
    alone so ordinary words never get expanded."""
    out = {}
    for w in re.findall(r"\b[A-Z][A-Z0-9]{1,9}s?\b", query):
        key = w.rstrip("s") if w.endswith("s") and w[:-1].isupper() else w
        try:
            row = conn.execute("SELECT expansion FROM acronyms WHERE acro=?",
                               (key,)).fetchone()
        except sqlite3.OperationalError:     # table not built yet
            return {}
        if row:
            out[key.lower()] = row[0]
    return out
