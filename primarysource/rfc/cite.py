"""Citation primitives: reference the spec, do not restate it.

Why this module exists: prose written *about* an RFC inside a library is a
second, uncheckable copy of the spec. It drifts when the RFC is updated, it
drifts when someone misremembers it, and nothing ever notices. A citation —
document, section, canonical URL, hash of the exact span — stays checkable
forever, and check() re-verifies it in a lookup.

So the policy this pushes toward:
  * cite the section for a rule (`RFC 2658 section 3.2`), never a summary of it;
  * quote verbatim (quote()) only when the exact wording is load-bearing, and
    carry the span hash so an upstream change becomes detectable;
  * do not paraphrase normative text (MUST/SHOULD sentences, ABNF, wire
    formats) into comments, docstrings or identifiers. That is the copy that
    rots silently, so lint() flags near-verbatim prose and uncited normative
    claims instead of pretending they are documentation.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import query as q
from .index import search as _s

NORM_KEYWORDS = ("MUST NOT", "MUST", "SHALL NOT", "SHALL", "SHOULD NOT",
                 "SHOULD NOT", "SHOULD", "MAY", "REQUIRED")
_WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9.'\-_]*")
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def label(doc_id: str) -> str:
    """'RFC2167' -> 'RFC 2167' (how a human writes it); 'BCP14' -> 'BCP 14'."""
    m = re.fullmatch(r"(RFC|BCP|STD|FYI)(\d+)", doc_id)
    return f"{m.group(1)} {int(m.group(2))}" if m else doc_id


def errata_note(conn: sqlite3.Connection, doc_id: str, sec: str = "") -> str:
    """Errata status for a doc or one section. Distinguishes 'none' from
    'nobody looked' — asserting zero verified errata when the service was
    never queried would be a false assurance."""
    rows = conn.execute(
        "SELECT status, section FROM errata WHERE doc_id=?",
        (doc_id,)).fetchall()
    if not rows:
        from .errata import bulk_synced_at
        at = bulk_synced_at(conn)
        return (f"errata: none (as of {at[:10]})" if at
                else f"errata: not cached (errata(ref='{doc_id}'))")
    verified = [r for r in rows if r["status"] == "Verified"]
    if not verified:
        return f"errata: 0 verified ({len(rows)} on file)"
    if sec:
        want = _s.norm_sec(sec)
        hit = [r for r in verified
               if want and want in (r["section"] or "").replace("\n", " ")]
        if hit:
            # the exact call, so an agent that has not loaded the errata
            # tool's schema copies the right argument name
            return (f"errata: {len(hit)} VERIFIED on this section — read "
                    f"them before implementing: errata(ref='{doc_id}§{want}')")
        return (f"errata: {len(verified)} verified elsewhere, "
                f"none on this section")
    return f"errata: {len(verified)} verified"


def _span(conn: sqlite3.Connection, doc_id: str, section: str | None,
          lines: str | None) -> dict:
    """Line span + anchor for a section reference, or an explicit 'a-b' line
    range when the caller has no section number to offer."""
    if section:
        if not conn.execute("SELECT 1 FROM chunks WHERE doc_id=? LIMIT 1",
                            (doc_id,)).fetchone():
            return {"ok": False, "reason": f"{doc_id} is not section-indexed "
                                           "(run `rfclib index build`)"}
        span = q._resolve_section_arg(conn, doc_id, section)
        if not span.get("ok"):
            return {"ok": False, "reason": span.get("reason"),
                    "suggestions": span.get("suggestions", []),
                    "outline": span.get("outline", [])}
        return {"ok": True, "sec_num": span["sec_num"],
                "sec_title": span.get("sec_title", ""),
                "start_line": span["start_line"], "end_line": span["end_line"],
                "frag": span.get("url_frag", "")}
    if lines:
        m = re.fullmatch(r"(\d+)\s*[-:]\s*(\d+)", lines.strip())
        if not m:
            return {"ok": False,
                    "reason": f"bad line range {lines!r} (want '1240-1288')"}
        return {"ok": True, "sec_num": "", "sec_title": "",
                "start_line": int(m.group(1)), "end_line": int(m.group(2)),
                "frag": ""}
    return {"ok": True, "sec_num": "", "sec_title": "", "start_line": 1,
            "end_line": 0, "frag": ""}


def span_text(conn: sqlite3.Connection, doc_id: str, *, mirror_root: Path,
              section: str | None = None, lines: str | None = None,
              mode: str = "clean") -> tuple[str, dict]:
    """The exact text of a span plus its resolved anchor metadata.

    mode='clean' (default) is the canonical form span_hash is defined over;
    mode='raw' is byte-exact against the RFC Editor file.
    """
    from .index.chunker import strip_page_furniture
    text, served, _p = q._served_text(conn, doc_id, "txt", mirror_root)
    sp = _span(conn, doc_id, section, lines)
    if text is None:
        return "", dict(sp, ok=False, reason="no local text copy")
    if not sp.get("ok"):
        return "", sp
    ls = text.splitlines()
    end = sp["end_line"] or len(ls)
    body = "\n".join(ls[sp["start_line"] - 1:end])
    if mode == "clean":
        body = strip_page_furniture(body)
    return body, dict(sp, ok=True, served_via=served, total_lines=len(ls))


def _authors_meta(conn, meta) -> str:
    return " and ".join(meta.get("authors") or [])


def cite(conn: sqlite3.Connection, doc_id: str, section: str | None = None,
         lines: str | None = None, style: str = "verbose", *,
         mirror_root: Path | None = None) -> str:
    """A canonical, checkable reference — the cheap substitute for pasting
    spec text into code.

    style: verbose (default) | short | markdown | comment | bibtex.
    'verbose' and 'comment' carry the span hash when mirror_root is given, so
    the citation can later be re-verified with verify().
    """
    row = q.get_doc_row(conn, doc_id)
    meta = q._row_to_meta(conn, row)
    sp = _span(conn, doc_id, section, lines)
    if not sp.get("ok") and style in ("verbose", "short", "comment",
                                      "markdown"):
        cands = ", ".join(sp.get("suggestions", [])) or "see get_toc"
        return (f"CANNOT CITE {label(doc_id)} \u00a7{section}: {sp['reason']}\n"
                f"candidates: {cands}")
    sec = sp.get("sec_num", "")
    title = meta.get("title") or ""
    date = (meta.get("pub_date") or "")[:7]
    url = q.anchor_url(meta, sp.get("frag") or "", q.resolve(conn, doc_id))
    secpart = f" \u00a7{sec}" + (f' "{sp["sec_title"]}"'
                                 if sp.get("sec_title") else "")
    linepart = (f" lines {sp['start_line']}-{sp['end_line']}" if lines else "")
    status = meta.get("current_status") or meta.get("status") or ""
    successor = ", ".join(meta["relations"].get("obsoleted_by", []))
    state = "current" if meta["is_current"] else \
        f"OBSOLETE by {successor or 'unknown'}"

    if style == "short":
        return f"{label(doc_id)}{secpart}{linepart}"
    if style == "markdown":
        return f"[{label(doc_id)}{secpart}{linepart}]({url})"
    if style == "bibtex":
        num = re.sub(r"\D", "", doc_id)
        series = ("Request for Comments" if doc_id.startswith("RFC")
                  else {"BCP": "Best Current Practice",
                        "STD": "Internet Standards",
                        "FYI": "FYI"}.get(doc_id[:3], "Request for Comments"))
        month = (_MONTHS[int(date[5:7]) - 1]
                 if len(date) >= 7 and date[5:7].isdigit() else "")
        rows = [f"@misc{{rfc{num},",
                f"  series =       {{{series}}},",
                f"  number =       {num},",
                f"  howpublished = {{{label(doc_id)}}},",
                "  publisher =    {RFC Editor},",
                f"  doi =          {{{meta.get('doi') or ''}}},",
                f"  url =          {{{meta.get('canonical_url') or ''}}},",
                f"  author =       {{{_authors_meta(conn, meta) or ''}}},",
                f"  title =        {{{{{title}}}}},"]
        if year := date[:4]:
            rows.append(f"  year =         {year},")
        if month:
            rows.append(f"  month =        {month},")
        rows.append("}")
        return "\n".join(rows)

    sha = ""
    if mirror_root is not None and (sec or lines):
        body, _ = span_text(conn, doc_id, mirror_root=mirror_root,
                            section=section, lines=lines)
        sha = f" | span sha256:{q.span_hash(body)}"
    tail = (f"{label(doc_id)}{secpart}{linepart} — {title} ({date}, "
            f"{status}, {state})\n{url} | "
            f"{errata_note(conn, doc_id, sec)}{sha}")
    if style == "comment":
        return "\n".join(("# " + ln) if ln else "#" for ln in tail.split("\n"))
    if not meta["is_current"]:
        tail += (f"\nWARNING: {label(doc_id)} is obsolete"
                 + (f"; cite {successor} instead" if successor else ""))
    return tail

