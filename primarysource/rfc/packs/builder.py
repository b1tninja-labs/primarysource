"""Build .rfcpack zips from collections.

Pack format v1 (mirrors caionline's .caipack: one root folder, one marker
file, verified manifest):

    <pack-id>/
      pack.json        manifest: metadata, per-doc files w/ sha256+size
      search.sqlite    optional: docs + chunks + FTS5 index over txt bodies
      docs/RFC9000.txt document files, one per fmt registered in pack.json

The Android reader verifies every file against sha256 on install and refuses
tampered/corrupt packs; catalog.json (see serve.py) carries pack-level sha256
for download verification. Everything is stdlib (zipfile, sqlite3, hashlib).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..index.chunker import split_sections
from ..sync.state import file_path
from .collections import Collection, resolve, sort_key

PACK_MARKER = "pack.json"
PACK_SUFFIX = ".rfcpack"
FORMAT_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


class MissingFiles(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        head = ", ".join(missing[:10])
        super().__init__(
            f"{len(missing)} docs have no local file "
            f"(run `rfclib sync` first): {head}"
            + (" ..." if len(missing) > 10 else ""))


def resolve_files(conn, doc_ids: list[str],
                  formats: list[str]) -> dict[str, dict[str, Path]]:
    """{doc_id: {fmt: local path}}; raises MissingFiles listing gaps."""
    out: dict[str, dict[str, Path]] = {}
    missing: list[str] = []
    for doc_id in doc_ids:
        per: dict[str, Path] = {}
        for fmt in formats:
            row = conn.execute(
                "SELECT path FROM files WHERE doc_id=? AND fmt=?",
                (doc_id, fmt)).fetchone()
            path = file_path(conn, row[0]) if row else None
            if path is None or not path.is_file():
                missing.append(f"{doc_id}.{fmt}")
            else:
                per[fmt] = path
        if per:
            out[doc_id] = per
    if missing:
        raise MissingFiles(missing)
    return out


def _docs_meta(conn, doc_ids: list[str],
               files: dict[str, dict[str, Path]]) -> list[dict]:
    docs = []
    for doc_id in doc_ids:
        row = conn.execute(
            """SELECT doc_id, series, title, status, pub_date, is_current,
                      stream, wg FROM docs WHERE doc_id=?""", (doc_id,)).fetchone()
        if row is None:
            continue
        docs.append({
            "doc_id": row["doc_id"], "series": row["series"],
            "title": row["title"] or "", "status": row["status"] or "",
            "pub_date": row["pub_date"] or "", "current": bool(row["is_current"]),
            "stream": row["stream"] or "", "wg": row["wg"] or "",
            "formats": sorted(files[doc_id]),
        })
    return docs


SEARCH_SCHEMA = """
CREATE TABLE docs(
  doc_id TEXT PRIMARY KEY, series TEXT, title TEXT, status TEXT,
  pub_date TEXT, is_current INTEGER, stream TEXT, wg TEXT);
CREATE TABLE chunks(
  id INTEGER PRIMARY KEY, doc_id TEXT NOT NULL,
  sec_num TEXT NOT NULL, sec_title TEXT NOT NULL,
  start_line INTEGER NOT NULL, end_line INT NOT NULL, body TEXT NOT NULL,
  sec TEXT GENERATED ALWAYS AS (trim(sec_num || ' ' || sec_title)) STORED);
CREATE INDEX idx_chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  sec, body, content='chunks', content_rowid='id',
  tokenize='porter unicode61 remove_diacritics 2');
"""


def build_search_db(doc_ids: list[str], txt_files: dict[str, Path],
                    out_path: Path) -> int:
    """Offline FTS5 index the app can open with android.database.sqlite."""
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(out_path)
    try:
        conn.executescript(SEARCH_SCHEMA)
        n_chunks = 0
        for doc_id in doc_ids:
            path = txt_files.get(doc_id)
            if path is None:
                continue
            text = path.read_text("utf-8", errors="replace")
            for sec in split_sections(text):
                conn.execute(
                    "INSERT INTO chunks(doc_id, sec_num, sec_title,"
                    " start_line, end_line, body) VALUES(?,?,?,?,?,?)",
                    (doc_id, sec.sec_num, sec.sec_title,
                     sec.start_line, sec.end_line, sec.text))
                n_chunks += 1
        conn.commit()
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
        conn.commit()
        conn.isolation_level = None  # VACUUM cannot run inside a transaction
        conn.execute("VACUUM")
        return n_chunks
    finally:
        conn.close()


def _fill_search_docs(search_db: Path, conn, doc_ids: list[str]) -> None:
    sc = sqlite3.connect(search_db)
    try:
        for doc_id in doc_ids:
            row = conn.execute(
                """SELECT doc_id, series, COALESCE(title,''),
                          COALESCE(status,''), COALESCE(pub_date,''),
                          is_current, COALESCE(stream,''), COALESCE(wg,'')
                   FROM docs WHERE doc_id=?""", (doc_id,)).fetchone()
            if row:
                sc.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?)",
                           tuple(row))
        sc.commit()
    finally:
        sc.close()


def build_pack(conn, coll: Collection, out_dir: Path,
               formats: list[str] = ("txt",), search: bool = True,
               progress=None) -> dict:
    """Build <out_dir>/<coll.id>.rfcpack; returns a summary dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc_ids = resolve(conn, coll)
    if not doc_ids:
        raise LookupError(f"collection '{coll.id}' resolves to 0 docs")
    # Alias-series docs (STD/BCP/FYI) are pointers, not content; drop any
    # that carry no member files instead of failing the whole pack.
    doc_ids = [d for d in doc_ids if d.startswith("RFC") or conn.execute(
        "SELECT 1 FROM files WHERE doc_id=? LIMIT 1", (d,)).fetchone()]
    files = resolve_files(conn, doc_ids, list(formats))
    doc_ids = [d for d in doc_ids if d in files]

    root = coll.id
    tmp = out_dir / (coll.id + PACK_SUFFIX + ".part")
    search_db = out_dir / f".search-{coll.id}.sqlite.tmp"
    n_chunks = 0
    try:
        if search and "txt" in files[doc_ids[0]]:
            txt = {d: files[d]["txt"] for d in doc_ids if "txt" in files[d]}
            if progress:
                progress(f"indexing {len(txt)} docs for offline search ...")
            n_chunks = build_search_db(doc_ids, txt, search_db)
            _fill_search_docs(search_db, conn, doc_ids)

        file_entries, hashes = [], []
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for doc_id in sorted(doc_ids, key=sort_key):
                for fmt, path in sorted(files[doc_id].items()):
                    arc = f"{root}/docs/{doc_id}.{fmt}"
                    sha = _sha256(path)
                    hashes.append(sha)
                    file_entries.append({
                        "path": arc, "doc_id": doc_id, "fmt": fmt,
                        "sha256": sha, "size": path.stat().st_size})
                    zf.write(path, arc)
            if search_db.is_file():
                zf.write(search_db, f"{root}/search.sqlite")
            manifest = {
                "format": FORMAT_VERSION,
                "id": coll.id, "name": coll.name,
                "description": coll.description,
                "generated_at": _now(),
                "formats": sorted(formats),
                "version": hashlib.sha256(
                    "".join(hashes).encode()).hexdigest()[:16],
                "doc_count": len(doc_ids), "chunk_count": n_chunks,
                "docs": _docs_meta(conn, doc_ids, files),
                "files": file_entries,
            }
            zf.writestr(f"{root}/{PACK_MARKER}",
                        json.dumps(manifest, ensure_ascii=False, indent=1))
        final = out_dir / (coll.id + PACK_SUFFIX)
        tmp.replace(final)
        return {"id": coll.id, "path": str(final), "docs": len(doc_ids),
                "files": len(file_entries), "chunks": n_chunks,
                "bytes": final.stat().st_size,
                "version": manifest["version"]}
    finally:
        if search_db.exists():
            search_db.unlink()
        if tmp.exists():
            tmp.unlink()
