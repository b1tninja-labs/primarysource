"""RFC Editor subject taxonomy (https://www.rfc-editor.org/subjects/).

The RFC Editor curates ~640 nested subjects ("web > http > http2") and
assigns every document to one or more of them. The taxonomy is only
published as HTML, so we mirror it into two tables:

  subjects(slug, name, parent, description, depth, doc_count)
      the tree as shown on /subjects/ (doc_count = upstream count,
      includes descendants)
  doc_subjects(doc_id, slug)
      per-document assignments mined from each /subjects/<slug>/ page

`sync()` fetches the index page plus one page per subject (rate-limited,
HTML cached under meta/subjects/ so re-parses are offline-safe) and
rebuilds both tables atomically. Query helpers back the MCP browsing
tools (list_subjects / get_subject / related).
"""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional

import httpx

from .config import BASE_URL, USER_AGENT, Paths, require_network

SUBJECTS_URL = f"{BASE_URL}/subjects/"

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects(
  slug        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  parent      TEXT,                    -- parent slug, NULL = top level
  description TEXT,
  depth       INTEGER NOT NULL DEFAULT 0,
  doc_count   INTEGER,                 -- upstream count (incl. descendants)
  ord         INTEGER                  -- upstream tree order for browsing
);
CREATE INDEX IF NOT EXISTS idx_subjects_parent ON subjects(parent);

CREATE TABLE IF NOT EXISTS doc_subjects(
  doc_id TEXT NOT NULL,
  slug   TEXT NOT NULL,
  PRIMARY KEY (doc_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_docsubj_slug ON doc_subjects(slug, doc_id);
"""

_TREE_UL_CLASS = "ml-6 border-l-1"  # nested child-subject lists in the index
_SUBJECT_HREF = re.compile(r"^/subjects/([^/]+)/?$")
_INFO_HREF = re.compile(r"/info/([A-Za-z]{2,4}\d+)/?")
_SERIES_ID = re.compile(r"^(rfc|bcp|std|fyi|ien)(\d{1,5})$", re.I)


class SubjectNotFound(Exception):
    pass


def ensure_schema(conn: sqlite3.Connection) -> None:
    # Look before writing: this runs on read paths (info, browse, search),
    # where a read-only server must not need a write, and executescript
    # would also commit whatever transaction the caller has open.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(subjects)")]
    if "ord" in cols and conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='idx_docsubj_slug'"
            ).fetchone():
        return
    conn.executescript(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(subjects)")]
    if "ord" not in cols:  # migration: pre-order column for tree browsing
        conn.execute("ALTER TABLE subjects ADD COLUMN ord INTEGER")


def subjects_ready(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' "
        "AND name='subjects'").fetchone()
    if not row or not row["c"]:
        return False
    return conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"] > 0



# --------------------------------------------------------------------------
# HTML parsing

class _IndexParser(HTMLParser):
    """Parse the /subjects/ tree page into subject rows.

    Only <ul> elements whose class contains the distinctive
    'ml-6 border-l-1' marker (the nested child lists) count toward
    nesting depth, so unrelated page <ul>s are ignored. Each subject
    entry is  <a href="/slug/">NAME</a> <span>NN RFCs</span>
    <p class="inline"> : description</p>  in document order; the nested
    child <ul> (if any) follows the parent's description inside the
    parent <li>. Vue comment markers (<!--[-->...) split text runs, so
    names/descriptions are buffered until the closing tag.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self._ul_stack: list[bool] = []
        self._depth = 0
        self._last_at_depth: dict[int, Optional[str]] = {}
        self._cur: Optional[dict] = None
        self._in_name = False
        self._in_count = False
        self._in_desc = False
        self._buf = ""

    def _flush(self) -> None:
        if self._cur is not None:
            self.rows.append(self._cur)
            self._cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "ul":
            is_tree = _TREE_UL_CLASS in (a.get("class") or "")
            self._ul_stack.append(is_tree)
            if is_tree:
                self._depth += 1
        elif tag == "a":
            m = _SUBJECT_HREF.match(a.get("href") or "")
            if m:
                self._flush()
                slug = m.group(1).lower()
                parent = self._last_at_depth.get(self._depth - 1) \
                    if self._depth > 0 else None
                self._last_at_depth[self._depth] = slug
                self._cur = {"slug": slug, "name": "", "parent": parent,
                             "depth": self._depth, "description": None,
                             "doc_count": None}
                self._in_name, self._buf = True, ""
        elif tag == "span" and self._cur is not None and not self._in_name:
            self._in_count, self._buf = True, ""
        elif tag == "p" and self._cur is not None \
                and (a.get("class") or "") == "inline":
            self._in_desc, self._buf = True, ""

    def handle_endtag(self, tag):
        if tag == "ul" and self._ul_stack:
            if self._ul_stack.pop():
                self._depth -= 1
        elif tag == "a" and self._in_name and self._cur is not None:
            self._cur["name"] = " ".join(self._buf.split())
            self._in_name = False
        elif tag == "span" and self._in_count and self._cur is not None:
            m = re.match(r"(\d+)", self._buf.strip())
            if m:
                self._cur["doc_count"] = int(m.group(1))
            self._in_count = False
        elif tag == "p" and self._in_desc:
            if self._cur is not None:
                desc = " ".join(self._buf.split())
                self._cur["description"] = re.sub(r"^:\s*", "", desc) or None
            self._in_desc = False

    def handle_data(self, data):
        if self._in_name or self._in_count or self._in_desc:
            self._buf += data

    def close(self):
        super().close()
        self._flush()


def parse_index(html_text: str) -> list[dict]:
    p = _IndexParser()
    p.feed(html_text)
    p.close()
    seen: set[str] = set()
    out = []
    for r in p.rows:
        if r["slug"] not in seen:  # tree order defines hierarchy
            seen.add(r["slug"])
            out.append(r)
    return out


def parse_subject_docs(html_text: str) -> list[str]:
    """Normalized doc_ids listed on a /subjects/<slug>/ page."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _INFO_HREF.finditer(html_text):
        mm = _SERIES_ID.match(m.group(1))
        if not mm:
            continue
        norm = mm.group(1).upper() + mm.group(2)
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out



# --------------------------------------------------------------------------
# sync

def _subject_dir(paths: Paths) -> Path:
    d = paths.meta / "subjects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(client: httpx.Client, url: str) -> str:
    require_network(f"the RFC Editor subject page {url}")
    r = client.get(url)
    r.raise_for_status()
    return r.text


def sync(conn: sqlite3.Connection, paths: Paths, force: bool = False,
         delay: float = 0.1, limit: int = 0,
         progress: Optional[Callable[[str], None]] = None) -> dict:
    """Mirror the subject taxonomy: index page + one page per subject.

    limit>0 restricts to the first N subjects (smoke runs; the index is
    always fetched). Cached HTML under meta/subjects/ is reused unless
    force=True. Both tables are rebuilt atomically at the end."""
    say = progress or (lambda m: None)
    ensure_schema(conn)
    cache = _subject_dir(paths)

    index_path = cache / "_index.html"
    if force or not index_path.exists():
        say("fetching subject index ...")
        with httpx.Client(headers={"User-Agent": USER_AGENT},
                          follow_redirects=True, timeout=60.0) as client:
            index_path.write_text(_get(client, SUBJECTS_URL), "utf-8")
    rows = parse_index(index_path.read_text("utf-8"))
    if not rows:
        raise RuntimeError(
            "subject index parsed to 0 rows - upstream layout may have "
            "changed; check data/meta/subjects/_index.html")
    if limit > 0:
        rows = rows[:limit]
    say(f"{len(rows)} subjects to crawl")

    doc_map: dict[str, list[str]] = {}
    failed: list[str] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT},
                      follow_redirects=True, timeout=60.0) as client:
        for i, r in enumerate(rows, 1):
            page = cache / f"{r['slug']}.html"
            try:
                if force or not page.exists():
                    page.write_text(
                        _get(client, f"{BASE_URL}/subjects/{r['slug']}/"),
                        "utf-8")
                    time.sleep(delay)
                doc_map[r["slug"]] = parse_subject_docs(
                    page.read_text("utf-8"))
            except Exception as exc:  # noqa: BLE001 - report, keep crawling
                failed.append(f"{r['slug']}:{type(exc).__name__}")
                doc_map[r["slug"]] = []
            if i % 50 == 0:
                say(f"crawled {i}/{len(rows)} subject pages")

    conn.execute("DELETE FROM subjects")
    conn.execute("DELETE FROM doc_subjects")
    n_assign = 0
    for i, r in enumerate(rows):
        conn.execute(
            "INSERT INTO subjects(slug,name,parent,description,depth,"
            "doc_count,ord) VALUES(?,?,?,?,?,?,?)",
            (r["slug"], r["name"], r["parent"], r["description"],
             r["depth"], r["doc_count"], i))
        for doc_id in doc_map.get(r["slug"], []):
            conn.execute(
                "INSERT OR IGNORE INTO doc_subjects(doc_id,slug) VALUES(?,?)",
                (doc_id, r["slug"]))
            n_assign += 1
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        ("subjects_synced_at", now))
    conn.commit()
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT doc_id) c FROM doc_subjects").fetchone()["c"]
    return {"subjects": len(rows), "assignments": n_assign,
            "distinct_docs": distinct, "failed": failed}



# --------------------------------------------------------------------------
# queries

def _subtree_slugs(conn: sqlite3.Connection, slug: str) -> list[str]:
    """slug plus all descendant slugs (iterative BFS, depth-safe)."""
    out = [slug]
    frontier = [slug]
    while frontier:
        ph = ",".join("?" * len(frontier))
        kids = [r["slug"] for r in conn.execute(
            f"SELECT slug FROM subjects WHERE parent IN ({ph})", frontier)]
        kids = [k for k in kids if k not in out]
        out.extend(kids)
        frontier = kids
    return out


def resolve_subject(conn: sqlite3.Connection, name: str) -> str:
    """Exact slug > exact name > unique substring. Raises SubjectNotFound."""
    ensure_schema(conn)
    s = name.strip().lower()
    row = conn.execute(
        "SELECT slug FROM subjects WHERE slug=?", (s,)).fetchone()
    if row:
        return row["slug"]
    row = conn.execute(
        "SELECT slug FROM subjects WHERE lower(name)=? LIMIT 1",
        (s,)).fetchone()
    if row:
        return row["slug"]
    like = f"%{s}%"
    rows = conn.execute(
        "SELECT slug, name FROM subjects WHERE slug LIKE ? OR lower(name)"
        " LIKE ? ORDER BY depth LIMIT 6", (like, like)).fetchall()
    if len(rows) == 1:
        return rows[0]["slug"]
    if rows:
        opts = ", ".join(f"{r['slug']} ({r['name']})" for r in rows)
        raise SubjectNotFound(
            f"subject {name!r} is ambiguous; candidates: {opts}")
    raise SubjectNotFound(f"no subject matches {name!r}; use list_subjects "
                          "to see the taxonomy")


def list_subjects(conn: sqlite3.Connection, contains: str | None = None,
                  limit: int = 700) -> list[dict]:
    ensure_schema(conn)
    limit = max(1, min(limit, 700))
    if contains:
        like = f"%{contains.strip().lower()}%"
        rows = conn.execute(
            """SELECT slug, name, parent, depth, doc_count, description
               FROM subjects
               WHERE lower(slug) LIKE ? OR lower(name) LIKE ?
                  OR lower(COALESCE(description,'')) LIKE ?
               ORDER BY ord LIMIT ?""",
            (like, like, like, limit)).fetchall()
    else:
        rows = conn.execute(
            """SELECT slug, name, parent, depth, doc_count, description
               FROM subjects ORDER BY ord LIMIT ?""",
            (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_subject(conn: sqlite3.Connection, name: str,
                include_obsolete: bool = False, limit: int = 50,
                offset: int = 0) -> dict:
    """Grouped listing for one subject incl. descendant subjects, mirroring
    the upstream /subjects/<slug>/ page but with local status/date data."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    slug = resolve_subject(conn, name)
    info = conn.execute(
        "SELECT * FROM subjects WHERE slug=?", (slug,)).fetchone()
    children = [dict(r) for r in conn.execute(
        "SELECT slug, name, doc_count FROM subjects WHERE parent=? "
        "ORDER BY slug", (slug,))]
    slugs = _subtree_slugs(conn, slug)
    ph = ",".join("?" * len(slugs))
    cond = "" if include_obsolete else "AND d.is_current = 1"
    total = conn.execute(
        f"""SELECT COUNT(DISTINCT ds.doc_id) c FROM doc_subjects ds
            JOIN docs d ON d.doc_id = ds.doc_id
            WHERE ds.slug IN ({ph}) {cond}""", slugs).fetchone()["c"]
    docs = [dict(r) for r in conn.execute(
        f"""SELECT DISTINCT d.doc_id, d.title, d.current_status, d.stream,
                   d.pub_date
            FROM doc_subjects ds JOIN docs d ON d.doc_id = ds.doc_id
            WHERE ds.slug IN ({ph}) {cond}
            ORDER BY d.pub_date DESC, d.doc_id DESC
            LIMIT ? OFFSET ?""", [*slugs, limit, offset]).fetchall()]
    return {
        "subject": {"slug": info["slug"], "name": info["name"],
                    "parent": info["parent"],
                    "description": info["description"],
                    "upstream_doc_count": info["doc_count"]},
        "children": children,
        "docs_total": total, "offset": offset, "docs": docs,
        "next_offset": offset + limit if offset + limit < total else None,
        "canonical_url": f"{BASE_URL}/subjects/{slug}/",
    }



def subjects_of(conn: sqlite3.Connection, doc_id: str) -> list[dict]:
    ensure_schema(conn)
    return [{"slug": r["slug"], "name": r["name"]} for r in conn.execute(
        "SELECT ds.slug, s.name FROM doc_subjects ds "
        "JOIN subjects s ON s.slug = ds.slug "
        "WHERE ds.doc_id = ? ORDER BY s.depth, s.slug", (doc_id,))]


def subjects_map(conn: sqlite3.Connection,
                 doc_ids: list[str]) -> dict[str, list[str]]:
    """doc_id -> [subject names] for a batch (one query; search hits)."""
    ensure_schema(conn)
    if not doc_ids:
        return {}
    out: dict[str, list[str]] = {d: [] for d in doc_ids}
    ph = ",".join("?" * len(doc_ids))
    for r in conn.execute(
            f"""SELECT ds.doc_id, s.name FROM doc_subjects ds
                JOIN subjects s ON s.slug = ds.slug
                WHERE ds.doc_id IN ({ph})
                ORDER BY s.depth, s.slug""", doc_ids):
        out[r["doc_id"]].append(r["name"])
    return out


def related(conn: sqlite3.Connection, doc_id: str, limit: int = 10) -> dict:
    """Subject-based neighborhood: docs sharing subjects (ranked by count
    of shared subjects) + sibling subjects popular in that neighborhood.
    Complements get_refs (citation graph) with topical similarity."""
    ensure_schema(conn)
    own = [r["slug"] for r in conn.execute(
        "SELECT slug FROM doc_subjects WHERE doc_id=?", (doc_id,))]
    if not own:
        return {"doc_id": doc_id, "subjects": [], "sibling_subjects": [],
                "nearby_docs": [],
                "note": "no subjects assigned for this doc (or taxonomy "
                        "not synced; run `rfclib subjects sync`)"}
    ph = ",".join("?" * len(own))
    siblings = [dict(r) for r in conn.execute(
        f"""SELECT ds.slug, s.name, COUNT(*) AS shares
            FROM doc_subjects ds
            JOIN subjects s ON s.slug = ds.slug
            WHERE ds.slug NOT IN ({ph})
              AND ds.doc_id IN (SELECT doc_id FROM doc_subjects
                                WHERE slug IN ({ph}))
            GROUP BY ds.slug ORDER BY shares DESC, ds.slug LIMIT 5""",
        [*own, *own]).fetchall()]
    nearby = [dict(r) for r in conn.execute(
        f"""SELECT d.doc_id, d.title, d.current_status, d.pub_date,
                   COUNT(*) AS shared_subjects
            FROM doc_subjects ds
            JOIN docs d ON d.doc_id = ds.doc_id
            WHERE ds.slug IN ({ph}) AND ds.doc_id != ? AND d.is_current = 1
            GROUP BY d.doc_id
            ORDER BY shared_subjects DESC, d.pub_date DESC
            LIMIT ?""", [*own, doc_id, max(1, min(limit, 50))]).fetchall()]
    return {"doc_id": doc_id, "subjects": own,
            "sibling_subjects": siblings, "nearby_docs": nearby}
