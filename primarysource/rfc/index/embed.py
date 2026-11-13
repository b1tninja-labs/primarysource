"""Semantic retrieval: local static embeddings (model2vec) + sqlite-vec KNN.

Everything stays inside the one SQLite DB and runs fully offline after the
first model download (~30 MB, Hugging Face). Vectors are L2-normalized so
sqlite-vec's default L2 distance orders identically to cosine similarity.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

DEFAULT_MODEL = "minishlab/potion-base-8M"

_model_cache: dict[str, object] = {}


def load_vec_extension(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as exc:
        raise RuntimeError(
            "semantic search is an optional feature and is not installed "
            "(pip install 'rfclib[semantic]'); search uses keywords, "
            "identifiers and titles meanwhile.") from exc
    try:
        conn.enable_load_extension(True)
    except (AttributeError, sqlite3.NotSupportedError) as exc:
        # some Python builds (macOS system Python, some pyenv builds)
        # compile SQLite without extension loading: keyword search only
        raise RuntimeError(
            "this Python's sqlite3 cannot load extensions, so semantic "
            "search is unavailable; search falls back to keywords. A uv- "
            "or python.org-installed Python supports it.") from exc
    try:
        sqlite_vec.load(conn)
    except sqlite3.OperationalError:
        pass  # already loaded on this connection
    finally:
        conn.enable_load_extension(False)


def model_dir(name: str = DEFAULT_MODEL):
    """<home>/models/<org>__<name>: the model travels with the library, so
    loading it never needs the network or a Hugging Face cache."""
    from ..config import Paths
    return Paths.default().models / name.replace("/", "__")


def get_model(name: str = DEFAULT_MODEL):
    if name not in _model_cache:
        try:
            from model2vec import StaticModel
        except ImportError as exc:     # callers treat RuntimeError as "no
            raise RuntimeError(        # semantic search": keyword fallback
                "semantic search is an optional feature and is not "
                "installed (pip install 'rfclib[semantic]').") from exc
        local = model_dir(name)
        if (local / "config.json").is_file():
            _model_cache[name] = StaticModel.from_pretrained(str(local))
            return _model_cache[name]
        try:
            # already in the Hugging Face cache: no etag revalidation
            model = StaticModel.from_pretrained(name, local_files_only=True)
        except Exception:
            from ..config import require_network
            require_network(f"the embedding model {name} (~30 MB)")
            model = StaticModel.from_pretrained(name)
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(str(local))
        except Exception:  # noqa: BLE001 - a cache miss next time, no more
            pass
        _model_cache[name] = model
    return _model_cache[name]


def ensure_vec_table(conn: sqlite3.Connection, dim: int) -> None:
    load_vec_extension(conn)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
        f"embedding float[{dim}])")


def embed_pending(conn: sqlite3.Connection, model_name: str = DEFAULT_MODEL,
                  limit: int = 0, batch: int = 256, progress=None,
                  doc_id: str | None = None) -> dict:
    """Embed chunks whose content changed since their last embedding
    (only those of doc_id when given: the on-demand path)."""
    try:
        import sqlite_vec
    except ImportError as exc:
        raise RuntimeError(
            "semantic search is an optional feature and is not installed "
            "(pip install 'rfclib[semantic]').") from exc
    rows = conn.execute(
        """SELECT c.id, c.body FROM chunks c
           LEFT JOIN embed_state e ON e.chunk_id = c.id
           WHERE (e.chunk_id IS NULL OR e.sha <> c.sha256 OR e.model <> ?)
             AND (? IS NULL OR c.doc_id = ?)
           ORDER BY c.id""", (model_name, doc_id, doc_id)).fetchall()
    if limit:
        rows = rows[:limit]
    stats = {"pending": len(rows), "embedded": 0}
    if not rows:
        return stats
    model = get_model(model_name)
    dim = int(model.encode(["dimension probe"], normalize=True).shape[1])
    ensure_vec_table(conn, dim)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = model.encode([r["body"][:4000] for r in part],
                            batch_size=len(part), normalize=True)
        for r, v in zip(part, vecs):
            conn.execute(
                "INSERT OR REPLACE INTO vec_chunks(rowid, embedding) "
                "VALUES(?,?)", (r["id"], sqlite_vec.serialize_float32(v)))
            conn.execute(
                "INSERT INTO embed_state(chunk_id, sha, model, at) "
                "VALUES(?,?,?,?) ON CONFLICT(chunk_id) DO UPDATE SET "
                "sha=excluded.sha, model=excluded.model, at=excluded.at",
                (r["id"], conn.execute(
                    "SELECT sha256 s FROM chunks WHERE id=?",
                    (r["id"],)).fetchone()["s"], model_name, now))
        conn.commit()
        stats["embedded"] += len(part)
        if progress:
            progress(stats["embedded"], len(rows))
    return stats


def semantic_search(conn: sqlite3.Connection, query: str, limit: int = 10,
                    include_obsolete: bool = False,
                    model_name: str = DEFAULT_MODEL) -> list[dict]:
    load_vec_extension(conn)
    n = conn.execute("SELECT COUNT(*) c FROM embed_state").fetchone()["c"]
    if n == 0:
        raise RuntimeError(
            "No embeddings built yet. Run `rfclib index embed` first.")
    import sqlite_vec
    model = get_model(model_name)
    qv = sqlite_vec.serialize_float32(
        model.encode([query], normalize=True)[0])
    sql = """
      SELECT v.rowid AS chunk_id, v.distance, c.doc_id, c.sec_num,
             c.sec_title, c.start_line, c.end_line, d.title, d.is_current,
             d.current_status,
             substr(replace(c.body, char(10), ' '), 1, 240) AS preview
      FROM vec_chunks v
      JOIN chunks c ON c.id = v.rowid
      JOIN docs  d ON d.doc_id = c.doc_id
      WHERE v.embedding MATCH ? AND k = ?"""
    params: list = [qv, max(limit * 4, 20)]
    if not include_obsolete:
        sql += " AND d.is_current = 1"
    sql += " ORDER BY v.distance"
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    # boilerplate sections sit deceptively close to every query vector:
    # push them out of the top of the list instead of trusting raw distance
    from .search import NOISE_TITLE_RE
    for r in rows:
        if NOISE_TITLE_RE.search(r["sec_title"] or ""):
            r["distance"] = r["distance"] + 0.35
    rows.sort(key=lambda r: r["distance"])
    return rows[:limit]