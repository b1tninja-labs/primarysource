"""Fetch each source and load it into the index. One source failing does not stop the others.

Each source is marked `syncing` before work and `ok` or `failed` after, so an interrupted run is reported as such by
every tool instead of looking like a complete corpus.

Network use is deliberately small: KEV uses an ETag, the CVE List is one daily baseline zip plus deltaLog-driven
single files, the kernel CNA is a shallow sparse git fetch, and EPSS is one 3 MB file. See docs/sources.md.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Any

from . import config, store
from .errors import CvelibError
from .kernel import parse_dyad
from .parse import parse_cve_record, parse_epss, parse_kev

# What a baseline sync needs on the disk holding CVELIB_HOME: the outer zip, the inner zip and the index.
CVELIST_NEED_BYTES = int(3.5 * 1024**3)
KERNEL_NEED_BYTES = int(0.6 * 1024**3)
# Above this many changed records a baseline is cheaper and kinder than that many single-file requests.
DELTA_FILE_LIMIT = 3000
DELTA_REQUEST_DELAY = 0.05
BASELINE_MAX_AGE_DAYS = 25
BATCH = 2000


@dataclass
class Response:
    status: int
    body: bytes
    headers: Message


Fetch = Callable[[str, dict[str, str]], Response]


def http_fetch(url: str, headers: dict[str, str]) -> Response:
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(request, timeout=300) as reply:
            return Response(reply.status, reply.read(), reply.headers)
    except urllib.error.HTTPError as error:
        if error.code == 304:
            return Response(304, b"", error.headers)
        raise CvelibError(
            f"HTTP {error.code} fetching {url}", "Try again later; this is not a local fault."
        ) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise CvelibError(f"network error fetching {url}: {error}", "Check connectivity and retry.") from error


def http_download(url: str, target: Path) -> None:
    """Stream a large file to `target` via a same-directory temporary, so a failure leaves nothing half-named."""
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT})
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=600) as reply, partial.open("wb") as out:
            shutil.copyfileobj(reply, out, 1024 * 1024)
    except (urllib.error.URLError, TimeoutError) as error:
        partial.unlink(missing_ok=True)
        raise CvelibError(f"download failed for {url}: {error}", "Check connectivity and retry.") from error
    partial.replace(target)


def check_disk(path: Path, need: int, force: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free
    if not force and free - need < config.min_free_bytes():
        raise CvelibError(
            f"{path} has {free / 1024**3:.1f} GB free; this sync needs about {need / 1024**3:.1f} GB and would leave "
            f"less than the {config.min_free_bytes() / 1024**3:.1f} GB reserve",
            "Set CVELIB_HOME to a larger disk, or pass --force, or lower CVELIB_MIN_FREE_GB.",
            status="disk",
        )


def _log(message: str) -> None:
    # stderr: stdout is the protocol when this runs under the MCP server's process.
    print(f"primarysource cve: {message}", file=sys.stderr, flush=True)


# ---- KEV -----------------------------------------------------------------------------------------------------


def sync_kev(conn: Any, fetch: Fetch = http_fetch, force: bool = False) -> str:
    previous = store.source_row(conn, "kev")
    headers: dict[str, str] = {}
    if previous is not None and previous["etag"] and previous["state"] == "ok" and not force:
        headers["If-None-Match"] = previous["etag"]
    store.mark_source(conn, "kev", "syncing", detail="fetching")
    reply = fetch(config.KEV_URL, headers)
    if reply.status == 304:
        store.mark_source(conn, "kev", "ok", detail="unchanged (ETag)")
        return "unchanged"
    version, released, entries = parse_kev(reply.body)
    store.replace_kev(conn, entries)
    store.mark_source(
        conn,
        "kev",
        "ok",
        version=version,
        upstream_date=released,
        records=len(entries),
        detail="catalog replaced",
        etag=reply.headers.get("ETag") or "",
    )
    return f"{len(entries)} entries, catalog {version}"


# ---- EPSS ----------------------------------------------------------------------------------------------------


def sync_epss(conn: Any, fetch: Fetch = http_fetch) -> str:
    store.mark_source(conn, "epss", "syncing", detail="fetching")
    reply = fetch(config.EPSS_URL, {})
    model, score_date, rows = parse_epss(reply.body)
    store.replace_epss(conn, rows)
    store.mark_source(
        conn, "epss", "ok", version=model, upstream_date=score_date, records=len(rows), detail="scores replaced"
    )
    return f"{len(rows)} scores, {score_date}"


# ---- Kernel CNA ----------------------------------------------------------------------------------------------

KERNEL_SPARSE = (
    "/cve/published/*/*.dyad",
    "/cve/published/*/*.json",
    "/cve/rejected/*/*.json",
    "/LICENSES/cve-tou.txt",
)


def _git(args: list[str], cwd: Path | None = None) -> str:
    # safe.directory: on a non-NTFS or differently owned disk git refuses a repository this process just created.
    repo = cwd.as_posix() if cwd is not None else "*"
    command = ["git", "-c", f"safe.directory={repo}", *args]
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise CvelibError(
            f"git {' '.join(args[:2])} failed: {done.stderr.strip()[:300]}", "Check connectivity and retry."
        )
    return done.stdout.strip()


def update_kernel_repo(repo: Path, force: bool) -> None:
    if (repo / ".git").is_dir():
        _git(["fetch", "--depth", "1", "origin", "HEAD"], repo)
        _git(["reset", "--hard", "FETCH_HEAD"], repo)
        return
    check_disk(repo.parent, KERNEL_NEED_BYTES, force)
    repo.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "--depth", "1", "--no-checkout", config.KERNEL_REPO_URL, str(repo)])
    _git(["sparse-checkout", "init", "--no-cone"], repo)
    _git(["sparse-checkout", "set", "--no-cone", *KERNEL_SPARSE], repo)
    _git(["checkout", "-q", "HEAD"], repo)


def ingest_kernel_tree(conn: Any, tree: Path, version: str, upstream_date: str) -> str:
    """Rebuild the kernel tables from a checkout. A CVE can move to `rejected/`, so nothing is kept from last time."""
    root = tree / "cve"
    if not root.is_dir():
        raise CvelibError(
            f"{tree} is not a checkout of the kernel CNA vulns repository",
            "Run: primarysource cve sync --source kernel",
        )
    store.clear_kernel(conn)
    published = rejected = 0
    for state, directory in (("PUBLISHED", root / "published"), ("REJECTED", root / "rejected")):
        for path in sorted(directory.glob("*/*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                _log(f"skipped unreadable {path.name}")
                continue
            record = parse_cve_record(data, state)
            if record is None:
                continue
            record.state = state if state == "REJECTED" else record.state
            store.put_record(conn, "kernel", record)
            if state == "PUBLISHED":
                dyad = path.with_suffix(".dyad")
                if dyad.is_file():
                    store.put_pairs(conn, record.cve, parse_dyad(dyad.read_text(encoding="utf-8")))
                published += 1
            else:
                rejected += 1
    store.mark_source(
        conn,
        "kernel",
        "ok",
        version=version,
        upstream_date=upstream_date,
        records=published,
        detail=f"{published} published, {rejected} rejected",
    )
    return f"{published} published, {rejected} rejected, commit {version[:12]}"


def sync_kernel(conn: Any, local_tree: Path | None = None, force: bool = False) -> str:
    store.mark_source(conn, "kernel", "syncing", detail="fetching")
    if local_tree is not None:
        return ingest_kernel_tree(conn, local_tree, "local-tree", "")
    repo = config.kernel_repo_dir()
    update_kernel_repo(repo, force)
    version, date = _git(["log", "-1", "--format=%H %cI"], repo).split()
    return ingest_kernel_tree(conn, repo, version, date)


# ---- CVE List ------------------------------------------------------------------------------------------------


def iter_zip_records(path: Path) -> Iterator[tuple[str, bytes]]:
    """`(name, json bytes)` for every CVE file in a release zip, opening the nested `cves.zip` when there is one."""
    with zipfile.ZipFile(path) as outer:
        inner_name = next((n for n in outer.namelist() if n.endswith("cves.zip")), None)
        if inner_name is None:
            yield from _iter_cve_members(outer)
            return
        inner_path = path.with_name(path.name + ".inner.zip")
        with outer.open(inner_name) as source, inner_path.open("wb") as out:
            shutil.copyfileobj(source, out, 1024 * 1024)
    try:
        with zipfile.ZipFile(inner_path) as inner:
            yield from _iter_cve_members(inner)
    finally:
        inner_path.unlink(missing_ok=True)


def _iter_cve_members(archive: zipfile.ZipFile) -> Iterator[tuple[str, bytes]]:
    for name in archive.namelist():
        stem = name.rsplit("/", 1)[-1]
        if stem.startswith("CVE-") and stem.endswith(".json"):
            yield stem, archive.read(name)


def load_records(conn: Any, items: Iterator[tuple[str, bytes]], source: str = "cvelist") -> tuple[int, int]:
    """Upsert CVE JSON documents, skipping any whose dateUpdated is what the index already holds."""
    known = store.existing_updated(conn, source)
    written = seen = 0
    for _name, body in items:
        try:
            data = json.loads(body)
        except ValueError:
            continue
        record = parse_cve_record(data)
        if record is None:
            continue
        seen += 1
        if known.get(record.cve) == record.updated and record.updated:
            continue
        store.put_record(conn, source, record)
        written += 1
        if written % BATCH == 0:
            conn.commit()
    conn.commit()
    return seen, written


def _latest_release(fetch: Fetch) -> dict[str, Any]:
    data = json.loads(fetch(config.CVELIST_RELEASE_API, {"Accept": "application/vnd.github+json"}).body)
    if not isinstance(data, dict):
        raise CvelibError("the GitHub release API returned something unexpected", "Retry later.")
    return data


def _asset(release: dict[str, Any], suffix: str) -> tuple[str, str] | None:
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if suffix in name:
            return name, str(asset.get("browser_download_url"))
    return None


def _parse_when(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _delta_targets(log: Any, since: datetime) -> list[str]:
    """The raw URLs of every record changed after `since`, deduplicated. `deltaLog.json` is newest first."""
    targets: dict[str, None] = {}
    if not isinstance(log, list):
        return []
    for entry in log:
        if not isinstance(entry, dict):
            continue
        when = _parse_when(str(entry.get("fetchTime") or ""))
        if when is None or when <= since:
            continue
        for key in ("new", "updated"):
            for item in entry.get(key) or []:
                if isinstance(item, dict) and item.get("githubLink"):
                    targets[str(item["githubLink"])] = None
    return list(targets)


def sync_cvelist(
    conn: Any,
    fetch: Fetch = http_fetch,
    download: Callable[[str, Path], None] = http_download,
    local_zip: Path | None = None,
    force: bool = False,
    full: bool = False,
) -> str:
    store.mark_source(conn, "cvelist", "syncing", detail="fetching")
    if local_zip is not None:
        seen, written = load_records(conn, iter_zip_records(local_zip))
        store.mark_source(conn, "cvelist", "ok", version=local_zip.name, records=_count(conn), detail="local zip")
        return f"{seen} records read, {written} written from {local_zip.name}"

    previous = store.source_row(conn, "cvelist")
    baseline_at = (
        _parse_when(str(previous["upstream_date"])) if previous is not None and previous["upstream_date"] else None
    )
    fresh_enough = (
        baseline_at is not None
        and datetime.now(UTC) - baseline_at < timedelta(days=BASELINE_MAX_AGE_DAYS)
        and previous is not None
        and previous["records"]
    )
    if not full and fresh_enough and baseline_at is not None:
        log = json.loads(fetch(config.CVELIST_DELTA_LOG, {}).body)
        targets = _delta_targets(log, baseline_at)
        if len(targets) <= DELTA_FILE_LIMIT:
            bodies: list[tuple[str, bytes]] = []
            for url in targets:
                bodies.append((url.rsplit("/", 1)[-1], fetch(url, {}).body))
                time.sleep(DELTA_REQUEST_DELAY)
            seen, written = load_records(conn, iter(bodies))
            newest = max(
                (w for e in log[:1] if (w := _parse_when(str(e.get("fetchTime") or ""))) is not None), default=None
            )
            when = newest.strftime("%Y-%m-%dT%H:%M:%SZ") if newest else None
            store.mark_source(
                conn,
                "cvelist",
                "ok",
                upstream_date=when,
                records=_count(conn),
                detail=f"deltaLog: {len(targets)} changed files, {written} written",
            )
            return f"delta: {len(targets)} changed, {written} written"
        _log(f"{len(targets)} changed files is past the delta limit; taking the baseline instead")

    check_disk(config.raw_dir(), CVELIST_NEED_BYTES, force)
    release = _latest_release(fetch)
    baseline = _asset(release, "_all_CVEs_at_midnight")
    delta = _asset(release, "_delta_CVEs_at_")
    if baseline is None:
        raise CvelibError("the latest CVE List release has no baseline asset", "See docs/sources.md and retry later.")
    name, url = baseline
    target = config.raw_dir() / "cvelist" / name
    _log(f"downloading {name}")
    download(url, target)
    try:
        seen, written = load_records(conn, iter_zip_records(target))
    finally:
        target.unlink(missing_ok=True)
    when = str(release.get("published_at") or "")
    if delta is not None:
        delta_body = fetch(delta[1], {}).body
        path = config.raw_dir() / "cvelist" / delta[0]
        path.write_bytes(delta_body)
        try:
            load_records(conn, iter_zip_records(path))
        finally:
            path.unlink(missing_ok=True)
    tag = str(release.get("tag_name") or "")
    store.mark_source(
        conn, "cvelist", "ok", version=tag, upstream_date=when, records=_count(conn), detail=f"baseline {name}"
    )
    return f"baseline {tag}: {seen} records read, {written} written"


def _count(conn: Any) -> int:
    row = conn.execute("SELECT count(*) FROM record WHERE source='cvelist'").fetchone()
    return int(row[0])


# ---- Orchestration -------------------------------------------------------------------------------------------


def sync(
    sources: list[str],
    kernel_tree: Path | None = None,
    cvelist_zip: Path | None = None,
    force: bool = False,
    full: bool = False,
) -> dict[str, str]:
    """Sync each named source. Returns `{source: outcome}`; a failed source is recorded and does not stop the rest."""
    unknown = sorted(set(sources) - set(config.SOURCES))
    if unknown:
        raise CvelibError(f"unknown source(s): {', '.join(unknown)}", f"Sources are: {', '.join(config.SOURCES)}")
    results: dict[str, str] = {}
    conn = store.open_write()
    try:
        for name in sources:
            started = time.monotonic()
            _log(f"syncing {name}")
            try:
                if name == "kev":
                    outcome = sync_kev(conn, force=force)
                elif name == "epss":
                    outcome = sync_epss(conn)
                elif name == "kernel":
                    outcome = sync_kernel(conn, kernel_tree, force)
                else:
                    outcome = sync_cvelist(conn, local_zip=cvelist_zip, force=force, full=full)
                conn.commit()
                results[name] = f"ok: {outcome} ({time.monotonic() - started:.0f}s)"
            except CvelibError as error:
                conn.rollback()
                store.mark_source(conn, name, "failed", detail=error.message)
                results[name] = f"FAILED: {error.message}"
    finally:
        conn.close()
    return results
