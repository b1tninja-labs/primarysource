"""Query API shared by the CLI and the MCP server. Everything reads the local
DB/mirror; content missing locally is fetched on demand from rfc-editor.org."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from . import subjects as subj
from .config import BASE_URL
from .sync import downloader
from .sync.state import file_path

DEFAULT_READ_CHARS = 6000


class NotFound(Exception):
    pass


def normalize_doc_id(raw: str) -> str:
    """Accept 'rfc 9000', '9000', 'RFC9000', 'bcp-14', 'std1' -> 'RFC9000' etc."""
    s = re.sub(r"[\s_/,]+", "", raw.strip().lower())
    if re.fullmatch(r"\d{1,5}", s):
        s = "rfc" + s
    m = re.fullmatch(r"(rfc|bcp|std|fyi|ien)(\d{1,5})", s)
    if not m:
        raise ValueError(f"not a valid RFC-series id: {raw!r}")
    return m.group(1).upper() + m.group(2)


def get_doc_row(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM docs WHERE doc_id = ?", (doc_id,)).fetchone()
    if row is None:
        raise NotFound(doc_id)
    return row


def resolve(conn: sqlite3.Connection, doc_id: str) -> str:
    """Follow is-also aliases (BCP/STD/FYI -> underlying RFC). Returns the
    doc_id whose content should be served."""
    cur = doc_id
    for _ in range(6):
        if cur.startswith("RFC"):
            return cur  # reached a content-bearing RFC; stop (avoids alias loops)
        rows = conn.execute(
            "SELECT dst FROM doc_relations WHERE src=? AND kind='alias'", (cur,)
        ).fetchall()
        if not rows:
            return cur
        targets = [r["dst"] for r in rows]
        best = next((t for t in targets if t.startswith("RFC")), None)
        if best is None or best == cur:
            return cur
        cur = best
    return cur


def _relations(conn: sqlite3.Connection, doc_id: str) -> dict[str, list[str]]:
    # The manifest records each obsoletes/updates pair from both sides; union
    # the direct and inverse views and de-duplicate.
    out: dict[str, set[str]] = {}
    for r in conn.execute(
            "SELECT kind, dst FROM doc_relations WHERE src=?", (doc_id,)):
        out.setdefault(r["kind"], set()).add(r["dst"])
    inverse = {"obsoletes": "obsoleted_by", "obsoleted_by": "obsoletes",
               "updates": "updated_by", "updated_by": "updates", "alias": "alias"}
    for r in conn.execute(
            "SELECT kind, src FROM doc_relations WHERE dst=?", (doc_id,)):
        out.setdefault(inverse[r["kind"]], set()).add(r["src"])
    return {k: sorted(v) for k, v in out.items()}


def _row_to_meta(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    d = dict(row)
    d["authors"] = json.loads(d.get("authors") or "[]")
    d["formats_offered"] = json.loads(d.get("formats") or "[]")
    d.pop("formats", None)
    d["formats_local"] = [
        r["fmt"] for r in conn.execute(
            "SELECT fmt FROM files WHERE doc_id=? ORDER BY fmt", (d["doc_id"],))]
    d["relations"] = _relations(conn, d["doc_id"])
    d["subjects"] = subj.subjects_of(conn, d["doc_id"])
    d["canonical_url"] = (
        f"{BASE_URL}/info/{d['doc_id'].lower()}" if d["series"] == "RFC"
        else f"{BASE_URL}/{d['series'].lower()}/{d['doc_id'].lower()}/")
    return d


def get_metadata(conn: sqlite3.Connection, doc_id: str) -> dict:
    row = get_doc_row(conn, doc_id)
    meta = _row_to_meta(conn, row)
    if row["series"] != "RFC":
        aliases = [a for a in meta["relations"].get("alias", []) if a != doc_id]
        if aliases:
            targets = []
            for a in aliases:
                try:
                    targets.append(get_metadata(conn, a))
                except NotFound:
                    pass
            if targets:
                meta["alias_of"] = targets
    return meta


def search(conn: sqlite3.Connection, q: str, limit: int = 10,
           include_obsolete: bool = False, stream: str | None = None,
           status: str | None = None,
           subject: str | None = None) -> list[dict]:
    limit = max(1, min(limit, 50))
    words = re.findall(r"[A-Za-z0-9]+", q)
    params: list = []
    where = []
    if not include_obsolete:
        where.append("d.is_current = 1")
    if stream:
        where.append("d.stream = ?")
        params.append(stream.upper())
    if status:
        where.append("(d.current_status LIKE ? OR d.status LIKE ?)")
        params += [f"%{status.upper()}%", f"%{status.upper()}%"]
    if subject:
        slugs = subj._subtree_slugs(conn, subj.resolve_subject(conn, subject))
        where.append("d.doc_id IN (SELECT doc_id FROM doc_subjects "
                     f"WHERE slug IN ({','.join('?' * len(slugs))}))")
        params.extend(slugs)
    tail = (" AND " + " AND ".join(where)) if where else ""

    rows: list[sqlite3.Row] = []
    if words:
        match = " AND ".join(f'"{w}"' for w in words)
        try:
            rows = conn.execute(
                f"""SELECT d.*, bm25(docs_fts) AS rank FROM docs_fts
                    JOIN docs d ON d.doc_id = docs_fts.doc_id
                    WHERE docs_fts MATCH ?{tail}
                    ORDER BY rank LIMIT ?""",
                [match, *params, limit]).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows and words:  # LIKE fallback (doc-number fragments etc.)
        like = f"%{q.strip()}%"
        rows = conn.execute(
            f"""SELECT d.* FROM docs d
                WHERE (d.doc_id LIKE ? OR d.title LIKE ?){tail}
                ORDER BY d.pub_date DESC LIMIT ?""",
            [like, like, *params, limit]).fetchall()
    return [_row_to_meta(conn, r) for r in rows]


def _content_path(conn: sqlite3.Connection, doc_id: str, fmt: str,
                  mirror_root: Path, fetch: bool) -> Path | None:
    row = conn.execute(
        "SELECT path FROM files WHERE doc_id=? AND fmt=?",
        (doc_id, fmt)).fetchone()
    if row:
        local = file_path(conn, row["path"], mirror_root)
        if local.exists():
            return local
    if not fetch:
        return None
    results = downloader.fetch_docs(conn, mirror_root, [doc_id], [fmt])
    conn.commit()
    for d, f, status in results:
        if status == "ok":
            rel = downloader.doc_relpath(d, f)
            if rel:
                return mirror_root / rel
    return None


def get_document(conn: sqlite3.Connection, doc_id: str, fmt: str = "txt",
                 mirror_root: Path | None = None, start_line: int = 1,
                 max_lines: int = 400) -> dict:
    """Return (possibly paginated) document text plus metadata flags."""
    row = get_doc_row(conn, doc_id)
    meta = _row_to_meta(conn, row)
    root = mirror_root if mirror_root is not None else Path("mirror")
    content_id = doc_id

    path = _content_path(conn, doc_id, fmt, root, fetch=True)
    if path is None:
        target = resolve(conn, doc_id)  # e.g. BCP14 -> RFC2119
        if target != doc_id:
            content_id = target
            path = _content_path(conn, target, fmt, root, fetch=True)

    if path is None:
        return {
            "doc_id": doc_id,
            "metadata": meta,
            "content": None,
            "note": f"no {fmt.upper()} rendering available from RFC Editor "
                    f"for this document; try format='txt' or get_metadata",
        }

    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    lines = text.splitlines()
    total = len(lines)
    start = max(1, start_line)
    chunk = "\n".join(lines[start - 1: start - 1 + max_lines])
    return {
        "doc_id": doc_id,
        "content_served_via": content_id if content_id != doc_id else None,
        "format": fmt,
        "path": str(path),
        "total_lines": total,
        "start_line": start,
        "end_line": min(total, start + max_lines - 1),
        "truncated": start - 1 + max_lines < total,
        "content": chunk,
        "is_obsolete": not bool(row["is_current"]),
        "obsoleted_by": meta["relations"].get("obsoleted_by", []),
        "metadata": {k: meta[k] for k in
                     ("title", "status", "current_status", "stream", "pub_date",
                      "authors", "doi", "errata_url", "canonical_url")},
    }


def span_hash(text: str) -> str:
    """16 hex chars of sha256 over the canonical span text (what quote()
    returns after page-furniture stripping). Short enough to live in a code
    comment, long enough to detect drift; files.sha256 stays authoritative
    for the whole document."""
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def _url_of(meta: dict) -> str:
    return meta.get("canonical_url") or ""


def anchor_url(meta: dict, frag: str = "", served: str | None = None) -> str:
    """URL that honours a section/paragraph fragment. The /info/ page has no
    section anchors, so fragments point at the RFC's HTML rendering (of the
    RFC that carries the text, for BCP/STD aliases)."""
    if not frag:
        return _url_of(meta)
    doc = served or meta["doc_id"]
    if not doc.startswith("RFC"):
        return _url_of(meta)
    return f"{BASE_URL}/rfc/{doc.lower()}.html#{frag}"


def _served_text(conn: sqlite3.Connection, doc_id: str, fmt: str,
                 mirror_root: Path) -> tuple[str | None, str, Path | None]:
    """(text, content_doc_id, path), following BCP/STD aliases to the RFC
    that carries the text. Missing files are fetched on demand."""
    path = _content_path(conn, doc_id, fmt, mirror_root, fetch=True)
    served = doc_id
    if path is None:
        target = resolve(conn, doc_id)
        if target != doc_id:
            served = target
            path = _content_path(conn, target, fmt, mirror_root, fetch=True)
    if path is None:
        return None, served, None
    text = path.read_text(encoding="utf-8", errors="replace")
    return text.lstrip("\ufeff"), served, path


def _fit(body: str, max_chars: int) -> tuple[str, int | None]:
    """Cut a text block at a line boundary; return (text, lines_shown+1)."""
    if len(body) <= max_chars:
        return body, None
    cut = body.rfind("\n", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    shown = body[:cut]
    return shown, shown.count("\n") + 1


def read_document(conn: sqlite3.Connection, doc_id: str, *,
                  mirror_root: Path, fmt: str = "txt",
                  section: str | None = None, start_line: int | None = None,
                  count: int | None = None, mode: str = "clean",
                  max_chars: int = DEFAULT_READ_CHARS,
                  deep: bool = True) -> str:
    """Plain text of a document or ONE section of it — returned as a string,
    because JSON-escaping a text block roughly doubles what it costs to read.

    section: '3.4', 'Appendix C', 'C.1', a range ('3.1/3.3') or a title
      substring ('ABNF') — resolved through the section index, so there is no
      line arithmetic and no page furniture to pay for.
    mode: 'clean' (default) drops running headers/footers and [Page N]
      markers (chunker.strip_page_furniture); 'raw' is byte-exact, which is
      what quote()/verify() use.
    max_chars is a hard budget and the result always ends with a footer
      naming the line to continue from — nothing disappears silently.
    Non-txt formats come back as a raw slice (section addressing is txt-only).
    """
    from .index import search as _s
    from .index.chunker import strip_page_furniture
    row = get_doc_row(conn, doc_id)
    text, served, _path = _served_text(conn, doc_id, fmt, mirror_root)
    meta = _row_to_meta(conn, row)
    if text is None:
        return (f"NO CONTENT: {doc_id} has no {fmt.upper()} rendering at the "
                f"RFC Editor. Try format='txt', or get_metadata.")
    obsolete = "" if meta["is_current"] else (
        " | OBSOLETE (superseded by "
        + (", ".join(meta["relations"].get("obsoleted_by", [])) or "n/a") + ")")
    lines = text.splitlines()
    total = len(lines)
    label, frag, sec_note = "", "", ""

    if fmt != "txt":
        start = max(1, start_line or 1)
        end = min(total, start + (count or 200) - 1)
        shown, nxt = _fit("\n".join(lines[start - 1:end]), max_chars)
        return (f"{doc_id} ({fmt}) | lines {start}-{end} of {total}{obsolete}\n"
                f"{_url_of(meta)}\n{shown}"
                + ("" if nxt is None else
                   f"\n[truncated at {max_chars} chars — continue with "
                   f"start_line={start + nxt}]"))

    if section:
        span = _resolve_section_arg(conn, served, section)
        if not span.get("ok"):
            extra = ""
            if span.get("suggestions"):
                extra = "\nsimilar sections: " + ", ".join(span["suggestions"])
            if span.get("outline"):
                extra += "\noutline: " + "; ".join(span["outline"][:20])
            return (f"NO SUCH SECTION: {doc_id} {section}\n"
                    f"{span.get('reason')}{extra}\n"
                    f"retry: read(doc_id='{doc_id}', section='<one of above>')")
        start, end = span["start_line"], span["end_line"]
        if not deep:
            rows = _s.section_rows(conn, served, section, deep=False)
            if rows:
                end = max(r["end_line"] for r in rows)
                sec_note = " (own text only, deep=False)"
        label = f" \u00a7{span['sec_num']}" + (
            f" \"{span['sec_title']}\"" if span.get("sec_title") else "")
        frag = span.get("url_frag", "")
    else:
        start = max(1, start_line or 1)
        end = min(total, start + (count or 300) - 1)

    body = "\n".join(lines[start - 1:end])
    if mode == "clean":
        body = strip_page_furniture(body)
    shown, nxt = _fit(body, max_chars)
    head = (f"{doc_id}{label} | lines {start}-{end} of {total}{sec_note} | "
            f"mode={mode} | sha256:{span_hash(body)}{obsolete}\n"
            f"{anchor_url(meta, frag, served)}\n")
    foot = ""
    if nxt is not None:
        foot = (f"\n[truncated at {max_chars} chars — continue with "
                f"start_line={start + nxt}"
                + (f", section='{section}'" if section else "") + "]")
    return head + shown + foot


def _resolve_section_arg(conn: sqlite3.Connection, doc_id: str,
                         section: str) -> dict:
    """resolve_span plus two conveniences callers always want: a range
    ('3.1/3.3') and a title substring ('ABNF', 'Security Considerations')."""
    from .index import search as _s
    if not section.strip().startswith("Appendix"):
        for sep in ("-", "\u2013", "/"):
            if sep not in section:
                continue
            a, b = [p.strip() for p in section.split(sep, 1)][:2]
            r1 = _s.resolve_span(conn, doc_id, a)
            r2 = _s.resolve_span(conn, doc_id, b)
            if r1.get("ok") and r2.get("ok"):
                return {"ok": True,
                        "sec_num": f"{r1['sec_num']}-{r2['sec_num']}",
                        "sec_title": "range", "start_line": r1["start_line"],
                        "end_line": r2["end_line"],
                        "url_frag": r1["url_frag"], "subsections": []}
    span = _s.resolve_span(conn, doc_id, section)
    if not span.get("ok") and span.get("indexed"):
        like = f"%{(section or '').strip().lower()}%"
        row = conn.execute(
            "SELECT sec_num, MIN(start_line) a, MAX(end_line) b FROM chunks "
            "WHERE doc_id=? AND lower(sec_title) LIKE ? AND sec_num <> '' "
            "GROUP BY sec_num ORDER BY a", (doc_id, like)).fetchone()
        if row:
            return {"ok": True, "sec_num": row["sec_num"],
                    "sec_title": section.strip().title(),
                    "start_line": row["a"], "end_line": row["b"],
                    "url_frag": _s.url_frag(row["sec_num"]),
                    "subsections": []}
    return span


def grep_document(conn: sqlite3.Connection, doc_id: str, pattern: str, *,
                  mirror_root: Path, ctx: int = 0, max_hits: int = 25,
                  ignore_case: bool = True,
                  max_chars: int = DEFAULT_READ_CHARS) -> str:
    """Every line matching a regex inside ONE document, labelled with the
    section it belongs to — the cheap way to locate an ABNF rule or keyword
    instead of paging through a spec hoping to land on it.

    Invalid regexes fall back to a literal search. A hit is citable as-is
    (section + line); follow up with read(section=...) rather than widening
    the grep.
    """
    import bisect
    import re as _re
    get_doc_row(conn, doc_id)
    try:
        rx = _re.compile(pattern, _re.I if ignore_case else 0)
        shown_pat = f"/{pattern}/"
    except _re.error:
        rx = _re.compile(_re.escape(pattern), _re.I if ignore_case else 0)
        shown_pat = f"{pattern!r} (literal)"
    text, served, _p = _served_text(conn, doc_id, "txt", mirror_root)
    if text is None:
        return f"NO CONTENT: {doc_id} has no local text copy."
    lines = text.splitlines()
    marks = [(r["start_line"],
              (f"{r['sec_num']} {r['sec_title']}".strip() or "front matter"))
             for r in conn.execute(
                 "SELECT DISTINCT start_line, sec_num, sec_title FROM chunks "
                 "WHERE doc_id=? ORDER BY start_line", (served,))]
    starts = [m[0] for m in marks]

    def sec_of(n: int) -> str:
        i = bisect.bisect_right(starts, n) - 1
        return marks[i][1] if i >= 0 else "(not section-indexed)"

    out, hits, shown_hits, i = [], 0, 0, 0
    while i < len(lines):
        if not rx.search(lines[i]):
            i += 1
            continue
        hits += 1
        if shown_hits < max_hits:
            lo, hi = max(0, i - ctx), min(len(lines), i + ctx + 1)
            out.append(f"{i + 1} [{sec_of(i + 1)}]")
            out.extend((">> " if j == i else "   ") + lines[j][:160]
                       for j in range(lo, hi))
            shown_hits += 1
        i += 1
    if not hits:
        return (f"NO MATCH for {shown_pat} in {doc_id} ({len(lines)} lines). "
                f"Try search_content to search the whole corpus, or loosen "
                f"the pattern.")
    body, _n = _fit("\n".join(out), max_chars)
    more = (f"\n[showing first {shown_hits} of {hits} matches — narrow the "
            f"pattern, or read the section above]" if shown_hits < hits else "")
    return (f"{hits} match(es) for {shown_pat} in {doc_id} "
            f"[{shown_hits} shown]\n{body}{more}")


def list_recent(conn: sqlite3.Connection, n: int = 20,
                series: str = "RFC") -> list[dict]:
    n = max(1, min(n, 100))
    rows = conn.execute(
        """SELECT * FROM docs
           WHERE series = ?
           ORDER BY pub_date DESC,
                    CAST(SUBSTR(doc_id, LENGTH(series) + 1) AS INTEGER) DESC
           LIMIT ?""",
        (series.upper(), n)).fetchall()
    return [_row_to_meta(conn, r) for r in rows]

