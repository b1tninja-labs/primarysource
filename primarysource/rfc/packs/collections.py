"""Collection manifests: named, editable bundles of RFCs resolved from the DB.

A collection is a small JSON file (stdlib-parseable — the Android reader
reads the same format) that names documents explicitly and/or selects them
by DB attributes (series/stream/area/wg/year). Publication is rolling
(~5-25 RFCs/month, no official batches), so the useful groupings are the
official ones: STD/BCP/FYI alias series, streams, IETF areas, working
groups, publication year — plus hand-curated sets like `essentials`.

Selector semantics (all keys optional, AND-combined):
  series / stream / area / wg : list of exact values to include
  year                        : pub_date year, e.g. "2025"
  current                     : true (default) keeps only non-obsolete docs
  members                     : true expands STD/BCP/FYI picks to their
                                content-bearing RFC members (alias edges)

Collection-level "history": also pull in the docs that the selected docs
obsolete (transitive), so a reader sees the lineage, not just the tip.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / "collections"

_SERIES_ORDER = {"RFC": 0, "BCP": 1, "STD": 2, "FYI": 3, "IEN": 4}


def sort_key(doc_id: str) -> tuple[int, int]:
    m = re.fullmatch(r"(RFC|BCP|STD|FYI|IEN)(\d+)", doc_id)
    if not m:
        return (9, 0)
    return (_SERIES_ORDER.get(m.group(1), 9), int(m.group(2)))


@dataclass
class Collection:
    id: str
    name: str
    description: str
    docs: list[str] = field(default_factory=list)
    selectors: list[dict] = field(default_factory=list)
    history: bool = False

    @classmethod
    def from_json(cls, raw: dict, fallback_id: str = "") -> "Collection":
        cid = raw.get("id") or fallback_id
        if not cid or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", cid):
            raise ValueError(f"invalid collection id: {cid!r}")
        return cls(
            id=cid,
            name=raw.get("name", cid),
            description=raw.get("description", ""),
            docs=[str(d) for d in raw.get("docs", [])],
            selectors=[dict(s) for s in raw.get("selectors", [])],
            history=bool(raw.get("history", False)),
        )


def builtin_collections() -> list[Path]:
    return sorted(BUILTIN_DIR.glob("*.json"))


def find_collection(name: str, extra_dirs: list[Path] | None = None) -> Path:
    """Locate `<name>.json` in the extra dirs (user dirs win) or builtins."""
    for d in (extra_dirs or []):
        p = Path(d) / f"{name}.json"
        if p.is_file():
            return p
    p = BUILTIN_DIR / f"{name}.json"
    if p.is_file():
        return p
    raise LookupError(f"no collection '{name}' (checked user dirs and builtins)")


def list_collections(extra_dirs: list[Path] | None = None) -> list[Collection]:
    """Builtins plus user overrides — a user file with the same id wins."""
    by_id: dict[str, Path] = {}
    for p in builtin_collections():
        by_id[p.stem] = p
    for d in (extra_dirs or []):
        for p in sorted(Path(d).glob("*.json")):
            by_id[p.stem] = p
    return [Collection.from_json(json.loads(path.read_text("utf-8")),
                                 fallback_id=cid)
            for cid, path in sorted(by_id.items())]


def _selector_sql(sel: dict) -> tuple[str, list]:
    where, args = ["1=1"], []
    for key in ("series", "stream", "area", "wg"):
        vals = sel.get(key)
        if vals:
            where.append(f"COALESCE({key},'') IN ({','.join('?' * len(vals))})")
            args += [str(v) for v in vals]
    year = sel.get("year")
    if year:
        where.append("pub_date LIKE ?")
        args.append(f"{int(year)}-%")
    if sel.get("current", True):
        where.append("is_current = 1")
    return " AND ".join(where), args


def _expand_members(conn, ids: set[str]) -> set[str]:
    """Replace STD/BCP/FYI alias docs by their content-bearing RFC members;
    aliases without any member edge are kept as-is."""
    if not ids:
        return ids
    ph = ",".join("?" * len(ids))
    nonrfc = {r[0] for r in conn.execute(
        f"SELECT doc_id FROM docs WHERE doc_id IN ({ph}) AND series != 'RFC'",
        sorted(ids))}
    if not nonrfc:
        return ids
    ph = ",".join("?" * len(nonrfc))
    members = {r[0] for r in conn.execute(
        f"SELECT dst FROM doc_relations WHERE kind='alias' AND src IN ({ph})",
        sorted(nonrfc))}
    by_alias: dict[str, list[str]] = {}
    for src, dst in conn.execute(
            f"SELECT src, dst FROM doc_relations "
            f"WHERE kind='alias' AND src IN ({ph})", sorted(nonrfc)):
        by_alias.setdefault(src, []).append(dst)
    out = set(ids)
    for alias in nonrfc:
        if by_alias.get(alias):
            out.discard(alias)
    return out | members


def resolve(conn, coll: Collection) -> list[str]:
    """Resolve a collection to a sorted list of doc_ids (no file checks)."""
    picked: set[str] = set()
    for doc in coll.docs:
        m = re.fullmatch(r"(RFC|BCP|STD|FYI|IEN)\s*(\d+)", doc.strip(), re.I)
        if not m:
            raise ValueError(f"{coll.id}: bad doc id {doc!r}")
        picked.add(m.group(1).upper() + m.group(2))
    for sel in coll.selectors:
        where, args = _selector_sql(sel)
        ids = {r[0] for r in conn.execute(
            f"SELECT doc_id FROM docs WHERE {where}", args)}
        if sel.get("members"):
            ids = _expand_members(conn, ids)
        picked |= ids

    if coll.history:
        # Add the docs the picked docs obsolete, transitively (lineage).
        frontier = set(picked)
        while frontier:
            ph = ",".join("?" * len(frontier))
            rows = conn.execute(
                f"""SELECT dst FROM doc_relations
                    WHERE kind='obsoletes' AND src IN ({ph})""",
                sorted(frontier)).fetchall()
            frontier = {r[0] for r in rows} - picked
            picked |= frontier
    return sorted(picked, key=sort_key)
