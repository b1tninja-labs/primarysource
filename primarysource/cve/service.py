"""The query layer behind both the CLI and the MCP server. Everything returns plain JSON-able dicts.

The merge rules live in `read`: description and affected data from the kernel CNA for kernel CVEs and from the CVE
List otherwise; CVSS listed per source with one preferred; KEV only from CISA's catalog; EPSS only from FIRST. Every
answer names its sources, and states what could not be consulted, because "no KEV entry" with an unsynced catalog is
a different fact from "not in KEV".
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from . import config, kernel, store
from .errors import CvelibError
from .kernel import Pair
from .parse import normalize_cve

SECTIONS = ("summary", "references", "affected", "kernel", "cvss", "sources")
LIMIT_MAX = 200
TOKENS_MAX = 8000
_REF = re.compile(r"^(CVE-\d{4}-\d{4,})(?:§([a-z]+)(?:¶(\d+))?)?$", re.IGNORECASE)
VERSION_ORDER = {"4.0": 4, "3.1": 3, "3.0": 2, "2.0": 1}


def _tokens(payload: object) -> int:
    return len(json.dumps(payload, ensure_ascii=False)) // 4


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _age_days(when: str | None) -> float | None:
    if not when:
        return None
    try:
        parsed = datetime.fromisoformat(when.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (datetime.now(UTC) - parsed).total_seconds() / 86400


def _sources(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {row["name"]: dict(row) for row in conn.execute("SELECT * FROM source")}


def _coverage(sources: Mapping[str, dict[str, Any]]) -> list[str]:
    """One line per source that is not fully usable. Empty means every source is synced and current."""
    gaps: list[str] = []
    for name in config.SOURCES:
        row = sources.get(name)
        if row is None:
            gaps.append(f"{name}: not synced (run: primarysource cve sync --source {name})")
        elif row["state"] != "ok":
            gaps.append(
                f"{name}: {row['state']} at {row['synced_at']}: {row['detail']} "
                f"(run: primarysource cve sync --source {name})"
            )
        else:
            age = _age_days(row["synced_at"])
            if age is not None and age > config.STALE_DAYS[name]:
                gaps.append(
                    f"{name}: stale, last synced {age:.0f} days ago (run: primarysource cve sync --source {name})"
                )
    return gaps


def _label(name: str, row: Mapping[str, Any] | None) -> str:
    if row is None:
        return name
    version = str(row["version"] or "")
    if name == "kernel" and version:
        return f"kernel CNA vulns.git {version[:12]}"
    if name == "cvelist":
        return f"CVE List {version}".strip()
    if name == "kev":
        return f"CISA KEV {version}".strip()
    if name == "epss":
        return f"FIRST EPSS {str(row['upstream_date'] or '')[:10]}".strip()
    return name


def _with_gaps(payload: dict[str, Any], sources: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    gaps = _coverage(sources)
    if gaps:
        payload["partial"] = gaps
    return payload


def _records(conn: sqlite3.Connection, cve: str) -> dict[str, dict[str, Any]]:
    return {row["source"]: dict(row) for row in conn.execute("SELECT * FROM record WHERE cve=?", (cve,))}


def _pairs(conn: sqlite3.Connection, cve: str) -> list[Pair]:
    rows = conn.execute("SELECT start, start_git, fix, fix_git FROM kernel_pair WHERE cve=?", (cve,)).fetchall()
    return [
        Pair(kernel.parse_version(row["start"]), row["start_git"], kernel.parse_version(row["fix"]), row["fix_git"])
        for row in rows
    ]


def _not_found(cve: str, sources: Mapping[str, dict[str, Any]]) -> CvelibError:
    gaps = _coverage(sources)
    hint = (
        "It may be reserved or newer than the last sync."
        if not gaps
        else "This corpus is incomplete: " + "; ".join(gaps)
    )
    return CvelibError(f"{cve} is in none of the synced sources", hint, status="not_found", partial=gaps)


def _preferred_metric(metrics: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A CNA's own score first, then CISA's ADP, then anything else; within those, the newest CVSS version."""

    def weight(metric: dict[str, Any]) -> tuple[int, int]:
        label = str(metric["label"])
        origin = 2 if label.startswith("CNA") else 1 if "CISA" in label else 0
        return origin, VERSION_ORDER.get(str(metric["version"]), 0)

    scored = [m for m in metrics if m["score"] is not None]
    return max(scored, key=weight) if scored else None


def _metrics(conn: sqlite3.Connection, cve: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM metric WHERE cve=? ORDER BY source", (cve,)).fetchall()
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = (row["label"], row["vector"])
        if key in seen:
            continue
        seen.add(key)
        unique.append({k: row[k] for k in ("label", "version", "vector", "score", "severity")})
    return unique


def _kev_block(conn: sqlite3.Connection, cve: str, sources: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    row = sources.get("kev")
    if row is None or row["state"] not in ("ok", "syncing"):
        return {"status": "unknown", "why": "the CISA KEV catalog is not synced"}
    entry = conn.execute("SELECT * FROM kev WHERE cve=?", (cve,)).fetchone()
    label = _label("kev", row)
    if entry is None:
        return {"status": "not_listed", "source": label}
    return {
        "status": "listed",
        "date_added": entry["date_added"],
        "due_date": entry["due_date"],
        "ransomware": entry["ransomware"],
        "action": entry["action"],
        "forensic_triage": entry["forensic_triage"],
        "source": label,
    }


def _epss_block(conn: sqlite3.Connection, cve: str, sources: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    row = sources.get("epss")
    if row is None:
        return None
    entry = conn.execute("SELECT score, percentile FROM epss WHERE cve=?", (cve,)).fetchone()
    if entry is None:
        return None
    return {"score": entry["score"], "percentile": entry["percentile"], "source": _label("epss", row)}


def _kernel_block(conn: sqlite3.Connection, cve: str, sources: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    pairs = _pairs(conn, cve)
    if not pairs:
        return None
    return {
        "source": _label("kernel", sources.get("kernel")),
        "fixed_in": kernel.fixed_in_by_branch(pairs),
        "unfixed_on_start": kernel.unfixed_starts(pairs),
        "ranges": [pair.text for pair in pairs],
    }


def _parse_ref(ref: str) -> tuple[str, str, int]:
    match = _REF.match(ref.strip())
    if match is None:
        normalize_cve(ref)  # raises the usual error
        return ref.strip().upper(), "summary", 1
    section = (match.group(2) or "summary").lower()
    if section not in SECTIONS:
        raise CvelibError(f"unknown section §{section}", f"Sections are: {', '.join(SECTIONS)}")
    return match.group(1).upper(), section, int(match.group(3) or 1)


def _cite(cve: str, used: dict[str, str]) -> str:
    return f"{cve} [{'; '.join(dict.fromkeys(used.values()))}]"


def _load(conn: sqlite3.Connection, record: dict[str, Any], key: str) -> Any:
    value = record.get(key)
    return json.loads(value) if value else []


def _page(
    items: list[Any], start: int, budget: int, ref: str, section: str, gather: dict[str, Any]
) -> dict[str, Any]:
    """A token-budgeted slice of `items` with the ref that continues it."""
    picked: list[Any] = []
    used = 0
    index = max(start, 1) - 1
    for item in items[index:]:
        cost = _tokens(item)
        if picked and used + cost > budget:
            break
        picked.append(item)
        used += cost
    end = index + len(picked)
    gather["total"] = len(items)
    gather["items"] = picked
    gather["start"] = index + 1
    if end < len(items):
        gather["next"] = f"{ref}§{section}¶{end + 1}"
    return gather


def read(ref: str, max_tokens: int = 2000) -> dict[str, Any]:
    cve, section, start = _parse_ref(ref)
    budget = _clamp(max_tokens, 200, TOKENS_MAX)
    conn = store.open_read()
    try:
        sources = _sources(conn)
        records = _records(conn, cve)
        if not records:
            kev = _kev_block(conn, cve, sources)
            if kev.get("status") == "listed":
                return _with_gaps(
                    {
                        "ref": cve,
                        "state": "UNKNOWN_TO_CVE_SOURCES",
                        "kev": kev,
                        "epss": _epss_block(conn, cve, sources),
                        "note": "only the KEV catalog has this id",
                    },
                    sources,
                )
            raise _not_found(cve, sources)
        # The kernel repository is the kernel CNA's own copy: it decides kernel CVEs even when the list copy differs.
        primary = records.get("kernel") or records["cvelist"]
        primary_source = "kernel" if "kernel" in records else "cvelist"
        attribution: dict[str, str] = {"record": _label(primary_source, sources.get(primary_source))}
        if "cvelist" in records:
            attribution["registry"] = _label("cvelist", sources.get("cvelist"))
        cvelist = records.get("cvelist")
        # Registry status wins for lifecycle: a CVE rejected upstream is rejected even if a mirror lags.
        state = (cvelist or primary)["state"]
        if "kernel" in records and records["kernel"]["state"] != state:
            state = "REJECTED" if "REJECTED" in {state, records["kernel"]["state"]} else state

        refs = list(dict.fromkeys(_load(conn, primary, "refs") + (_load(conn, cvelist, "refs") if cvelist else [])))
        affected = (
            _load(conn, (cvelist or primary), "affected")
            if primary_source == "cvelist"
            else _load(conn, primary, "affected")
        )
        metrics = _metrics(conn, cve)
        kernel_block = _kernel_block(conn, cve, sources)

        if section == "references":
            return _with_gaps(_page(refs, start, budget, cve, section, {"ref": f"{cve}§references"}), sources)
        if section == "affected":
            return _with_gaps(
                _page(
                    affected, start, budget, cve, section, {"ref": f"{cve}§affected", "source": attribution["record"]}
                ),
                sources,
            )
        if section == "cvss":
            return _with_gaps(
                {"ref": f"{cve}§cvss", "items": metrics, "preferred": _preferred_metric(metrics)}, sources
            )
        if section == "kernel":
            if kernel_block is None:
                return _with_gaps(
                    {"ref": f"{cve}§kernel", "kernel": None, "note": "no kernel CNA data for this CVE"}, sources
                )
            ranges = kernel_block.pop("ranges")
            return _with_gaps(
                _page(ranges, start, budget, cve, section, {"ref": f"{cve}§kernel", **kernel_block}), sources
            )
        if section == "sources":
            return _with_gaps(
                {
                    "ref": f"{cve}§sources",
                    "sources": {
                        name: {
                            "version": row["version"],
                            "upstream_date": row["upstream_date"],
                            "synced_at": row["synced_at"],
                            "state": row["state"],
                        }
                        for name, row in sources.items()
                    },
                },
                sources,
            )

        epss_row = _epss_block(conn, cve, sources)
        kev_row = _kev_block(conn, cve, sources)
        if kev_row.get("status") != "unknown":
            attribution["kev"] = str(kev_row.get("source"))
        if epss_row:
            attribution["epss"] = str(epss_row.get("source"))
        files = str(primary.get("files") or "").split()
        result: dict[str, Any] = {
            "ref": cve,
            "cite": _cite(cve, attribution),
            "state": state,
            "assigner": primary["assigner"] or (cvelist or primary)["assigner"],
            "published": (cvelist or primary)["published"],
            "updated": (cvelist or primary)["updated"],
            "title": primary["title"],
            "description": primary["description"],
            "description_source": attribution["record"],
            "cwe": _load(conn, primary, "cwes") or (_load(conn, cvelist, "cwes") if cvelist else []),
            "cvss": {"preferred": _preferred_metric(metrics), "count": len(metrics)},
            "kev": kev_row,
            "epss": epss_row,
            "ssvc": _load(conn, cvelist or primary, "ssvc") or None,
            "kernel": None,
            "sources_used": attribution,
            "references": refs[:8],
            "references_total": len(refs),
        }
        if kernel_block is not None:
            result["kernel"] = {
                "source": kernel_block["source"],
                "fixed_in": kernel_block["fixed_in"],
                "unfixed_on_start": kernel_block["unfixed_on_start"],
                "files": files[:12],
                "files_total": len(files),
                "use": f"cve_kernel('{cve}', '<version>')",
            }
        if len(refs) > 8:
            result["next"] = f"{cve}§references¶1"
        if _tokens(result) > budget:
            result["description"] = result["description"][: max(budget * 2, 400)]
            result["references"] = result["references"][:3]
            result["truncated"] = True
        result["sections"] = [f"{cve}§{name}" for name in SECTIONS[1:]]
        return _with_gaps(result, sources)
    finally:
        conn.close()


def search(
    query: str,
    limit: int = 8,
    start: int = 0,
    kev_only: bool = False,
    kernel_only: bool = False,
    year: int = 0,
    max_tokens: int = 1500,
) -> dict[str, Any]:
    text = query.strip()
    if not text:
        raise CvelibError("an empty query matches nothing", "Give search terms, a file path or a CVE id.")
    limit = _clamp(limit, 1, LIMIT_MAX)
    budget = _clamp(max_tokens, 200, TOKENS_MAX)
    conn = store.open_read()
    try:
        sources = _sources(conn)
        if not (sources.get("cvelist") or sources.get("kernel")):
            raise CvelibError(
                "no CVE records have been synced",
                "Run: primarysource cve sync --source cvelist,kernel",
                status="not_synced",
                partial=_coverage(sources),
            )
        if re.fullmatch(r"(?i)CVE-\d{4}-\d{4,}", text):
            cve = text.upper()
            if conn.execute("SELECT 1 FROM record WHERE cve=? LIMIT 1", (cve,)).fetchone():
                return _with_gaps(
                    {"query": text, "hits": [_hit(conn, cve, "", sources, None)], "exact": True}, sources
                )

        clauses = ["record.state != 'REJECTED'"]
        args: list[Any] = []
        if kev_only:
            clauses.append("record.cve IN (SELECT cve FROM kev)")
        if kernel_only:
            clauses.append("record.cve IN (SELECT cve FROM kernel_pair)")
        if year:
            clauses.append("record.cve LIKE ?")
            args.append(f"CVE-{year}-%")

        terms = [term for term in re.findall(r'"[^"]+"|\S+', text)]
        phrases = [f'"{term.strip(chr(34)).replace(chr(34), "")}"' for term in terms]
        strict = " ".join(phrases)
        loose = " OR ".join(phrases)
        rows, relaxed = [], False
        for expression, was_relaxed in ((strict, False), (loose, True)):
            rows = _fts(conn, expression, clauses, args, start + limit * 6 + 50)
            if rows:
                relaxed = was_relaxed
                break
            if len(phrases) == 1:
                break

        seen: dict[str, sqlite3.Row] = {}
        for row in rows:
            seen.setdefault(row["cve"], row)
        ordered = list(seen.values())
        chosen = ordered[start : start + limit]
        hits: list[dict[str, Any]] = []
        used = 0
        for row in chosen:
            hit = _hit(conn, row["cve"], row["snip"], sources, row["source"])
            cost = _tokens(hit)
            if hits and used + cost > budget:
                break
            hits.append(hit)
            used += cost
        payload: dict[str, Any] = {"query": text, "hits": hits}
        if relaxed:
            payload["relaxed"] = "only some terms matched"
        if start + len(hits) < len(ordered):
            payload["next"] = {"start": start + len(hits)}
        return _with_gaps(payload, sources)
    finally:
        conn.close()


def _fts(
    conn: sqlite3.Connection, expression: str, clauses: list[str], args: list[Any], fetch: int
) -> list[sqlite3.Row]:
    sql = (
        "SELECT record.cve AS cve, record.source AS source, "
        "snippet(fts, 1, '', '', '...', 24) AS snip, bm25(fts, 8.0, 1.0, 4.0, 4.0) AS rank "
        "FROM fts JOIN record ON record.rowid = fts.rowid WHERE fts MATCH ? AND "
        + " AND ".join(clauses)
        + " ORDER BY rank LIMIT ?"
    )
    try:
        return conn.execute(sql, [expression, *args, fetch]).fetchall()
    except sqlite3.OperationalError as error:
        raise CvelibError(f"could not run that search: {error}", "Use plain words or quoted phrases.") from error


def _hit(
    conn: sqlite3.Connection, cve: str, snippet: str, sources: Mapping[str, dict[str, Any]], origin: str | None
) -> dict[str, Any]:
    records = _records(conn, cve)
    best = records.get("kernel") or records.get("cvelist") or next(iter(records.values()))
    metrics = _metrics(conn, cve)
    preferred = _preferred_metric(metrics)
    hit: dict[str, Any] = {
        "ref": cve,
        "title": best["title"] or best["description"][:90],
        "source": "kernel" if "kernel" in records else (origin or "cvelist"),
    }
    if snippet:
        hit["snippet"] = snippet
    if preferred:
        hit["cvss"] = preferred["score"]
    if conn.execute("SELECT 1 FROM kev WHERE cve=?", (cve,)).fetchone():
        hit["kev"] = True
    epss = conn.execute("SELECT score FROM epss WHERE cve=?", (cve,)).fetchone()
    if epss:
        hit["epss"] = epss["score"]
    return hit


def kev(ref: str = "", vendor: str = "", since: str = "", limit: int = 20, start: int = 0) -> dict[str, Any]:
    limit = _clamp(limit, 1, LIMIT_MAX)
    conn = store.open_read()
    try:
        sources = _sources(conn)
        row = sources.get("kev")
        if row is None or row["state"] == "failed":
            raise CvelibError(
                "the CISA KEV catalog is not synced, so KEV status cannot be determined",
                "Run: primarysource cve sync --source kev",
                status="not_synced",
            )
        label = _label("kev", row)
        if ref:
            cve = normalize_cve(ref)
            entry = conn.execute("SELECT * FROM kev WHERE cve=?", (cve,)).fetchone()
            if entry is None:
                return _with_gaps({"ref": cve, "status": "not_listed", "source": label}, sources)
            data = dict(entry)
            data["cwes"] = json.loads(data["cwes"] or "[]")
            return _with_gaps({"ref": cve, "status": "listed", "source": label, **data}, sources)
        clauses: list[str] = []
        args: list[Any] = []
        if vendor:
            clauses.append("(vendor LIKE ? OR product LIKE ?)")
            args += [f"%{vendor}%", f"%{vendor}%"]
        if since:
            clauses.append("date_added >= ?")
            args.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(f"SELECT count(*) FROM kev {where}", args).fetchone()[0]  # noqa: S608
        rows = conn.execute(
            f"SELECT cve, vendor, product, name, date_added, due_date, ransomware FROM kev {where} "  # noqa: S608
            "ORDER BY date_added DESC, cve DESC LIMIT ? OFFSET ?",
            [*args, limit, start],
        ).fetchall()
        payload: dict[str, Any] = {"source": label, "total": total, "items": [dict(item) for item in rows]}
        if start + len(rows) < total:
            payload["next"] = {"start": start + len(rows)}
        return _with_gaps(payload, sources)
    finally:
        conn.close()


def kernel_check(ref: str, version: str) -> dict[str, Any]:
    """Does this CVE affect this kernel version? Kernel CNA data when it exists, otherwise a clearly hedged answer."""
    cve = normalize_cve(ref)
    parsed = kernel.parse_version(version)
    caveats = kernel.version_caveats(version)
    conn = store.open_read()
    try:
        sources = _sources(conn)
        records = _records(conn, cve)
        pairs = _pairs(conn, cve)
        answer: dict[str, Any] = {"ref": cve, "version": version}
        if caveats:
            answer["caveats"] = caveats
        kernel_row = sources.get("kernel")
        if pairs:
            verdict = kernel.explain(pairs, parsed)
            answer.update(
                {
                    "verdict": "affected" if verdict.affected else "not_affected",
                    "reason": verdict.reason,
                    "detail": verdict.detail,
                    "evidence": list(verdict.evidence),
                    "fixed_in": kernel.fixed_in_by_branch(pairs),
                    "source": _label("kernel", kernel_row),
                    "confidence": "high",
                    "note": "Per-branch data from the kernel CNA, including stable backports.",
                }
            )
            return _with_gaps(answer, sources)

        record = records.get("cvelist") or records.get("kernel")
        if record is None:
            raise _not_found(cve, sources)
        if "kernel" in records and record is records["kernel"] and records["kernel"]["state"] == "REJECTED":
            answer.update(
                {"verdict": "rejected", "reason": "rejected_by_kernel_cna", "source": _label("kernel", kernel_row)}
            )
            return _with_gaps(answer, sources)
        affected = _load(conn, record, "affected")
        kernel_entries = [entry for entry in affected if kernel.is_kernel_product(entry)]
        if not kernel_entries:
            answer.update(
                {
                    "verdict": "unknown",
                    "reason": "not_a_kernel_record",
                    "detail": "no kernel CNA data, and the CVE List record does not name the Linux kernel",
                    "source": _label("cvelist", sources.get("cvelist")),
                    "confidence": "none",
                }
            )
            return _with_gaps(answer, sources)
        matches, usable = kernel.fallback_ranges(kernel_entries, parsed)
        source = _label("cvelist", sources.get("cvelist"))
        if usable == 0:
            answer.update(
                {
                    "verdict": "unknown",
                    "reason": "wildcard_record",
                    "detail": "the record names the kernel but gives no version range; it is not evidence either way",
                    "source": source,
                    "confidence": "none",
                }
            )
        elif matches:
            answer.update(
                {
                    "verdict": "possibly_affected",
                    "reason": "cna_range_match",
                    "detail": "version falls in a range from the assigning CNA, which rarely tracks stable backports",
                    "evidence": matches[:6],
                    "source": source,
                    "confidence": "low",
                    "note": "Not the kernel CNA: a longterm kernel may already carry the fix. Check the changelog.",
                }
            )
        else:
            answer.update(
                {
                    "verdict": "unknown",
                    "reason": "outside_cna_ranges",
                    "detail": "version is outside the assigning CNA's ranges, which does not prove it is unaffected",
                    "source": source,
                    "confidence": "low",
                }
            )
        return _with_gaps(answer, sources)
    finally:
        conn.close()


def kernel_list(
    version: str, kev_only: bool = False, path: str = "", limit: int = 25, start: int = 0, max_tokens: int = 2000
) -> dict[str, Any]:
    """Every kernel CNA CVE that affects `version`, known-exploited first, then by EPSS."""
    parsed = kernel.parse_version(version)
    limit = _clamp(limit, 1, LIMIT_MAX)
    budget = _clamp(max_tokens, 200, TOKENS_MAX)
    conn = store.open_read()
    try:
        sources = _sources(conn)
        if not (sources.get("kernel") and sources["kernel"]["state"] == "ok"):
            raise CvelibError(
                "kernel CNA data is not synced, so a version cannot be assessed",
                "Run: primarysource cve sync --source kernel",
                status="not_synced",
                partial=_coverage(sources),
            )
        grouped: dict[str, list[Pair]] = {}
        for row in conn.execute("SELECT cve, start, start_git, fix, fix_git FROM kernel_pair"):
            grouped.setdefault(row["cve"], []).append(
                Pair(
                    kernel.parse_version(row["start"]),
                    row["start_git"],
                    kernel.parse_version(row["fix"]),
                    row["fix_git"],
                )
            )
        affected: dict[str, kernel.Verdict] = {}
        for cve, pairs in grouped.items():
            verdict = kernel.explain(pairs, parsed)
            if verdict.affected:
                affected[cve] = verdict
        kev_ids = {row[0] for row in conn.execute("SELECT cve FROM kev")}
        epss = {row[0]: row[1] for row in conn.execute("SELECT cve, score FROM epss")}
        files_filter = path.strip()
        titles = {
            row["cve"]: (row["title"], str(row["files"] or ""))
            for row in conn.execute("SELECT cve, title, files FROM record WHERE source='kernel'")
        }
        order = sorted(affected, key=lambda c: (c not in kev_ids, -epss.get(c, 0.0), c))
        if kev_only:
            order = [c for c in order if c in kev_ids]
        if files_filter:
            order = [c for c in order if files_filter in titles.get(c, ("", ""))[1]]
        items: list[dict[str, Any]] = []
        used = 0
        for cve in order[start : start + limit]:
            title, files = titles.get(cve, ("", ""))
            item: dict[str, Any] = {"ref": cve, "title": title, "why": affected[cve].detail}
            if cve in kev_ids:
                item["kev"] = True
            if cve in epss:
                item["epss"] = epss[cve]
            if files:
                item["files"] = files.split()[:3]
            cost = _tokens(item)
            if items and used + cost > budget:
                break
            items.append(item)
            used += cost
        payload: dict[str, Any] = {
            "version": version,
            "source": _label("kernel", sources.get("kernel")),
            "affected_total": len(order),
            "assessed": len(grouped),
            "items": items,
        }
        caveats = kernel.version_caveats(version)
        if caveats:
            payload["caveats"] = caveats
        if start + len(items) < len(order):
            payload["next"] = {"start": start + len(items)}
        payload["note"] = (
            "Covers CVEs assigned by the kernel CNA only. Compiled-in reachability depends on the build's config."
        )
        return _with_gaps(payload, sources)
    finally:
        conn.close()


def info(ref: str = "") -> dict[str, Any]:
    """Corpus status; with `ref`, a one-screen card for that CVE."""
    home = config.home()
    index = config.index_path()
    if not index.is_file():
        return {
            "home": str(home),
            "status": "not_synced",
            "error": "no index yet",
            "hint": "Run: primarysource cve sync (set CVELIB_HOME to a large disk first)",
        }
    conn = store.open_read()
    try:
        sources = _sources(conn)
        if ref:
            cve = normalize_cve(ref)
            records = _records(conn, cve)
            if not records:
                raise _not_found(cve, sources)
            best = records.get("kernel") or records.get("cvelist") or next(iter(records.values()))
            metrics = _metrics(conn, cve)
            preferred = _preferred_metric(metrics)
            kev_row = _kev_block(conn, cve, sources)
            return _with_gaps(
                {
                    "ref": cve,
                    "state": best["state"],
                    "title": best["title"] or best["description"][:120],
                    "cvss": preferred,
                    "kev": kev_row.get("status"),
                    "epss": _epss_block(conn, cve, sources),
                    "kernel_cna": cve
                    in {row[0] for row in conn.execute("SELECT DISTINCT cve FROM kernel_pair WHERE cve=?", (cve,))},
                    "next": f"cve_read('{cve}')",
                },
                sources,
            )
        counts = {
            "cve_list_records": conn.execute("SELECT count(*) FROM record WHERE source='cvelist'").fetchone()[0],
            "kernel_records": conn.execute("SELECT count(*) FROM record WHERE source='kernel'").fetchone()[0],
            "kernel_ranges": conn.execute("SELECT count(*) FROM kernel_pair").fetchone()[0],
            "kev_entries": conn.execute("SELECT count(*) FROM kev").fetchone()[0],
            "epss_scores": conn.execute("SELECT count(*) FROM epss").fetchone()[0],
        }
        size = index.stat().st_size
        payload: dict[str, Any] = {
            "home": str(home),
            "index": str(index),
            "index_mb": round(size / 1024 / 1024, 1),
            "counts": counts,
            "sources": {
                name: {
                    "state": row["state"],
                    "version": row["version"],
                    "upstream_date": row["upstream_date"],
                    "synced_at": row["synced_at"],
                    "records": row["records"],
                    "detail": row["detail"],
                }
                for name, row in sources.items()
            },
        }
        return _with_gaps(payload, sources)
    finally:
        conn.close()
