"""Library lifecycle: what is on disk, how it gets there, what it can answer.

A library fills in tiers, and every view works with whatever tier exists:

  catalog    `rfclib init`: the RFC index (rfc-index.xml), bulk errata and
             the RFC Editor subject tree. Status, obsolete chains, info,
             document search, browse and errata work for every RFC.
  on demand  the first read/grep/outline/cite/links of an RFC fetches its
             txt (and RFCXML for RFC 8650+) from rfc-editor.org, segments
             and indexes it in well under a second, and keeps it.
  synced     `rfclib sync` / `rfclib init --content ...` prefetch documents
             in bulk, so full-text section search covers them all.

Nothing here runs at import time, and the MCP server never blocks startup
on it: an empty library answers with what to do instead of "no matches".
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import NetworkDisabled, Paths, network_mode, read_only


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state(conn: sqlite3.Connection) -> dict:
    from .sync.state import get_meta
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
    subjects = 0
    if one("SELECT COUNT(*) FROM sqlite_master WHERE name='subjects'"):
        subjects = one("SELECT COUNT(*) FROM subjects")
    return {
        "docs": one("SELECT COUNT(*) FROM docs"),
        "rfcs": one("SELECT COUNT(*) FROM docs WHERE series='RFC'"),
        "current_rfcs": one("SELECT COUNT(*) FROM docs WHERE series='RFC' "
                            "AND is_current=1"),
        "txt_local": one("SELECT COUNT(*) FROM files WHERE fmt='txt'"),
        "indexed": one("SELECT COUNT(*) FROM chunk_src"),
        "indexed_current": one(
            "SELECT COUNT(*) FROM chunk_src s JOIN docs d USING(doc_id) "
            "WHERE d.is_current=1 AND d.series='RFC'"),
        "embedded_chunks": one("SELECT COUNT(*) FROM embed_state"),
        "errata": one("SELECT COUNT(*) FROM errata"),
        "subjects": subjects,
        "manifest_synced_at": get_meta(conn, "manifest_synced_at"),
        "errata_synced_at": get_meta(conn, "errata_bulk_synced_at"),
        "subjects_synced_at": get_meta(conn, "subjects_synced_at"),
        "network": network_mode(),
    }


def features() -> dict[str, bool]:
    """Optional components (pip extras) available in this environment."""
    import importlib.util as u
    return {
        "mcp": u.find_spec("mcp") is not None,
        "semantic": (u.find_spec("model2vec") is not None
                     and u.find_spec("sqlite_vec") is not None),
        "zim": u.find_spec("libzim") is not None,
    }


def initialized(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM docs LIMIT 1").fetchone() is not None


def not_initialized_message(conn: sqlite3.Connection | None = None) -> str:
    home = Paths.default().home
    msg = (f"The RFC library at {home} is empty. Run `rfclib init` once (the "
           "RFC index, errata and subject tree, about a minute); RFCs are "
           "then fetched on first use. `rfclib init --content current` also "
           "prefetches every current RFC for full-text search (~10 min).")
    if _bootstrap.running:
        msg = ("The RFC library is being initialized in the background "
               f"({_bootstrap.step}); retry in a minute.")
    return msg


def coverage_note(conn: sqlite3.Connection) -> str:
    """'' when section search covers (nearly) every current RFC, else a
    line saying what was searched, for the top of search results."""
    s = conn.execute(
        "SELECT (SELECT COUNT(*) FROM docs WHERE series='RFC' AND "
        "is_current=1), (SELECT COUNT(*) FROM chunk_src s JOIN docs d "
        "USING(doc_id) WHERE d.is_current=1 AND d.series='RFC')").fetchone()
    total, done = s[0], s[1]
    if not total or done >= total * 0.95:
        return ""
    return (f"coverage: section search covers the {done:,} of {total:,} "
            "current RFCs fetched so far. scope='documents' searches all of "
            "them; read() fetches any RFC on demand; `rfclib sync` "
            "prefetches the rest.")


# --------------------------------------------------------------------------
# on demand

_fetch_locks: dict[str, threading.Lock] = {}
_fetch_guard = threading.Lock()


def ensure_indexed(conn: sqlite3.Connection, doc_id: str) -> bool:
    """Make doc_id readable: fetch its files if missing (RFC 8650+ also gets
    its RFCXML for exact structure), segment and index it, embed its
    sections if the model is already on disk. True when the document is
    indexed afterwards. Raises NetworkDisabled when it would need the
    network and RFCLIB_NETWORK=offline."""
    if conn.execute("SELECT 1 FROM chunk_src WHERE doc_id=?",
                    (doc_id,)).fetchone():
        return True
    if read_only():         # indexing is a write; the shared server does it
        raise NetworkDisabled(
            f"{doc_id} is not indexed in this library and this server is "
            "read-only (RFCLIB_READONLY); read it through the shared rfclib "
            "server once, or run `rfclib sync && rfclib index build`.")
    with _fetch_guard:
        lock = _fetch_locks.setdefault(doc_id, threading.Lock())
    with lock:
        if conn.execute("SELECT 1 FROM chunk_src WHERE doc_id=?",
                        (doc_id,)).fetchone():
            return True
        from . import graph, query as q
        from .index import search as ix_search
        from .sync.state import mirror_of
        mirror = mirror_of(conn)
        txt = q._content_path(conn, doc_id, "txt", mirror, fetch=True)
        if txt is None:
            return False
        row = conn.execute("SELECT formats FROM docs WHERE doc_id=?",
                           (doc_id,)).fetchone()
        if row and "xml" in (row["formats"] or ""):
            try:
                q._content_path(conn, doc_id, "xml", mirror, fetch=True)
            except (NetworkDisabled, OSError):
                pass            # txt structure is a fine fallback
        ok = ix_search.index_doc(conn, doc_id)
        try:
            graph.build(conn, [doc_id])
        except Exception:  # noqa: BLE001 - citations are a bonus here
            pass
        _embed_if_model_present(conn, doc_id)
        return ok


def _embed_if_model_present(conn: sqlite3.Connection, doc_id: str) -> None:
    """Never download a 30 MB model inside a tool call: embed only when the
    model is already in the library (rfclib init --content / index embed)."""
    from .index import embed as ix_embed
    if not (ix_embed.model_dir() / "config.json").is_file():
        return
    try:
        ix_embed.embed_pending(conn, doc_id=doc_id)
    except Exception:  # noqa: BLE001 - semantic search is optional
        pass


# --------------------------------------------------------------------------
# init: the catalog tier, then optional bulk content

def init_catalog(conn: sqlite3.Connection, paths: Paths, *,
                 subjects: bool = True, refresh: bool = False,
                 say=lambda m: None) -> dict:
    """RFC index + errata + subject tree. Each step is idempotent and skips
    work already done, so an interrupted init simply resumes."""
    from . import errata as errata_mod, subjects as subj_mod
    from .sync.manifest import download_manifest, parse_manifest
    from .sync.state import (rebuild_fts, refresh_current_flags, set_meta,
                             upsert_docs)
    out: dict = {}
    _bootstrap.step = "RFC index"
    say("RFC index (rfc-index.xml, ~14 MB) ...")
    dest = download_manifest(paths.manifest_xml, force=refresh)
    n_docs, n_rel = upsert_docs(conn, parse_manifest(dest))
    refresh_current_flags(conn)
    rebuild_fts(conn)
    set_meta(conn, "manifest_synced_at", _now())
    from .index.lexical import mine_acronyms
    out["acronyms"] = mine_acronyms(conn)     # titles/abstracts: seconds
    out["documents"], out["relations"] = n_docs, n_rel

    _bootstrap.step = "errata"
    if refresh or not errata_mod.bulk_synced_at(conn):
        say("errata (RFC Editor bulk feed, ~12 MB) ...")
        try:
            out["errata"] = errata_mod.sync_bulk(conn)["errata"]
        except NetworkDisabled:
            out["errata"] = "skipped (offline)"

    if subjects:
        _bootstrap.step = "subject tree"
        if refresh or not subj_mod.subjects_ready(conn):
            say("subject tree (rfc-editor.org/subjects, ~640 pages, "
                "a few minutes; cached and resumable) ...")
            res = subj_mod.sync(conn, paths, progress=say)
            out["subjects"] = res.get("subjects", res)
    return out


def init_content(conn: sqlite3.Connection, paths: Paths, scope: str, *,
                 embed: bool = True, say=lambda m: None,
                 concurrency: int = 8) -> dict:
    """Prefetch documents and build the full indexes. scope: current (every
    RFC not obsoleted) | all (including obsolete)."""
    from . import graph
    from .index import embed as ix_embed, search as ix_search
    from .sync import downloader
    from .sync.state import missing_docs
    out: dict = {}
    inc_obs = scope == "all"
    for fmt in ("txt", "xml"):
        todo = missing_docs(conn, [fmt], include_obsolete=inc_obs)
        if todo:
            _bootstrap.step = f"downloading {len(todo)} {fmt} files"
            say(f"downloading {len(todo):,} {fmt} files from rfc-editor.org ...")
            res = downloader.fetch_docs(conn, paths.mirror, todo, [fmt],
                                        concurrency=concurrency)
            out[f"{fmt}_ok"] = sum(1 for _, _, s in res if s == "ok")
    _bootstrap.step = "indexing sections"
    say("indexing sections (RFCXML for RFC 8650+, ToC-driven for older) ...")
    out["index"] = ix_search.build_chunks(conn, paths.mirror)
    say("mining citations ...")
    out["refs"] = graph.build(conn)
    if embed:
        _bootstrap.step = "embedding"
        say("embedding sections (model ~30 MB, kept in the library) ...")
        try:
            out["embed"] = ix_embed.embed_pending(conn)
        except RuntimeError as e:   # rfclib[semantic] not installed
            out["embed"] = f"skipped: {e}"
    return out


# --------------------------------------------------------------------------
# optional background bootstrap for the MCP server (RFCLIB_AUTO_INIT=1)

class _Bootstrap:
    running = False
    step = ""
    error = ""
    _lock = threading.Lock()

    def start(self, paths: Paths) -> bool:
        """Start a catalog init in a background thread once per process.
        Opt-in: an MCP server that downloads on its own surprises people."""
        if os.environ.get("RFCLIB_AUTO_INIT", "") not in ("1", "true", "yes"):
            return False
        if network_mode() == "offline":
            return False
        with self._lock:
            if self.running:
                return True
            self.running, self.error, self.step = True, "", "starting"
        threading.Thread(target=self._run, args=(paths,), daemon=True).start()
        return True

    def _run(self, paths: Paths) -> None:
        from .fsutil import LockHeld, bulk_lock
        from .sync.state import open_db
        try:
            with bulk_lock(paths.home):
                conn = open_db(paths.db)
                # index + errata only (seconds); the ~640-page subject crawl
                # stays an explicit `rfclib init`
                init_catalog(conn, paths, subjects=False)
        except LockHeld:
            self.error = "another rfclib process is initializing"
        except Exception as e:  # noqa: BLE001 - reported via status
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.running, self.step = False, ""


_bootstrap = _Bootstrap()


def maybe_bootstrap(conn: sqlite3.Connection) -> None:
    if not initialized(conn):
        _bootstrap.start(Paths.default().ensure())


def _home(conn: sqlite3.Connection) -> Path:
    from .sync.state import mirror_of
    return mirror_of(conn).parent
