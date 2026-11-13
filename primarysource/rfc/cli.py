"""rfclib command-line interface."""

from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import errata as errata_mod
from . import graph
from . import query as q
from .config import Paths
from .index import embed as ix_embed, hybrid as ix_hybrid, search as ix_search
from .packs import builder as pack_builder
from .packs import collections as pack_collections
from .packs import epub as pack_epub, export as pack_export
from .packs import htmlexport as pack_html, docsetexport as pack_docset
from .packs import serve as pack_serve
from .sync import downloader, scanner
from .sync.manifest import download_manifest, parse_manifest
from .sync.state import (db_stats, missing_docs, open_db, rebuild_fts,
                         refresh_current_flags, set_meta, upsert_docs)

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Local RFC library "
                       "(official RFC Editor sources: rfc-editor.org)")
console = Console()


def _version_cb(value: bool):
    # eager callback: fires during option processing, i.e. before click
    # demands a subcommand, so `rfclib --version` works standalone.
    if value:
        from . import __version__
        console.print(f"rfclib {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_cb, is_eager=True,
        help="Print the rfclib version and exit."),
):
    """Root callback; --version is handled by the eager option callback."""



def _paths() -> Paths:
    return Paths.default().ensure()


@contextlib.contextmanager
def _locked(paths: Paths):
    """One bulk writer per library (init, sync, index build/embed)."""
    from .fsutil import LockHeld, bulk_lock
    try:
        with bulk_lock(paths.home):
            yield
    except LockHeld as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(code=1)


def _legacy_hint() -> None:
    from .config import legacy_home
    old = legacy_home()
    if old:
        console.print(f"[yellow]note:[/yellow] a library from an older rfclib "
                      f"exists at {old}; this command uses "
                      f"{Paths.default().home}. To keep using the old one: "
                      f"set RFCLIB_HOME={old}")


def _db(paths: Paths):
    return open_db(paths.db)


def _did(raw: str) -> str:
    """normalize_doc_id with a clean CLI error instead of a traceback."""
    try:
        return q.normalize_doc_id(raw)
    except ValueError as e:
        raise typer.BadParameter(str(e))


def _load_manifest(paths: Paths, conn, refresh: bool) -> None:
    dest = download_manifest(paths.manifest_xml, force=refresh)
    docs = parse_manifest(dest)
    n_docs, n_rel = upsert_docs(conn, docs)
    refresh_current_flags(conn)
    n_fts = rebuild_fts(conn)
    set_meta(conn, "manifest_synced_at",
             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    console.print(f"[green]manifest indexed:[/green] {n_docs} docs, "
                  f"{n_rel} relations, {n_fts} FTS rows (source: {dest})")


@app.command()
def manifest(refresh: bool = typer.Option(False, "--refresh",
               help="Force re-download of rfc-index.xml")):
    """Fetch/parse the official RFC Index manifest into the local DB."""
    paths = _paths()
    conn = _db(paths)
    _load_manifest(paths, conn, refresh)


@app.command()
def init(content: str = typer.Option(
             "none", "--content",
             help="also prefetch documents: none (catalog only; RFCs are "
                  "fetched on first use) | current | all"),
         subjects: bool = typer.Option(
             True, "--subjects/--no-subjects",
             help="crawl the RFC Editor subject tree (~640 pages, cached)"),
         embed: bool = typer.Option(
             True, "--embed/--no-embed",
             help="with --content: build semantic vectors (~30 MB model)"),
         refresh: bool = typer.Option(
             False, "--refresh", help="re-fetch catalog data even if present")):
    """Set up the library: catalog first, documents optional; re-runnable.

    The catalog (RFC index, errata, subject tree) makes status, search by
    document, browse and errata work for every RFC; documents are then
    fetched on first use. Finished steps are skipped on a re-run."""
    from . import library
    if content not in ("none", "current", "all"):
        raise typer.BadParameter("--content must be none, current or all")
    _legacy_hint()
    paths = _paths()
    conn = _db(paths)
    console.print(f"library: [bold]{paths.home}[/bold]")
    t0 = time.time()
    say = lambda m: console.print(f"  {m}", highlight=False)  # noqa: E731
    with _locked(paths):
        out = library.init_catalog(conn, paths, subjects=subjects,
                                   refresh=refresh, say=say)
        if content != "none":
            out["content"] = library.init_content(conn, paths, content,
                                                  embed=embed, say=say)
    console.print(f"[green]done[/green] in {time.time() - t0:.0f}s: "
                  f"{json.dumps(out, default=str)[:400]}")
    console.print(escape("next: `rfclib status`; MCP clients run "
                         "`uvx --from 'rfclib[mcp,semantic]' rfclib mcp`"),
                  highlight=False)


@app.command()
def sync(formats: str = typer.Option("txt", help="comma list: txt,html,xml,pdf,json"),
         limit: int = typer.Option(0, help="max documents this run (0 = all)"),
         include_obsolete: bool = typer.Option(False, help="also fetch obsolete RFCs"),
         concurrency: int = typer.Option(8, min=1, max=16),
         force: bool = typer.Option(False, help="re-download even if present"),
         refresh_manifest: bool = typer.Option(False, "--refresh-manifest")):
    """Incremental sync: fetch documents missing from the local mirror."""
    paths = _paths()
    conn = _db(paths)
    fmts = [f.strip().lower() for f in formats.split(",") if f.strip()]
    bad = [f for f in fmts if f not in downloader.VALID_FORMATS]
    if bad:
        raise typer.BadParameter(f"unsupported formats: {bad}")
    if refresh_manifest or conn.execute(
            "SELECT COUNT(*) c FROM docs").fetchone()["c"] == 0:
        _load_manifest(paths, conn, refresh=True)

    missing = missing_docs(conn, fmts, include_obsolete=include_obsolete)
    if limit:
        missing = missing[:limit]
    if not missing:
        console.print("[green]mirror already complete[/green] for requested formats")
        return
    console.print(f"syncing [bold]{len(missing)}[/bold] docs ({'+'.join(fmts)}) "
                  "from rfc-editor.org ...")
    t0 = time.time()
    with _locked(paths):
        results = downloader.fetch_docs(conn, paths.mirror, missing, fmts,
                                        concurrency=concurrency, force=force)
    conn.commit()
    ok = sum(1 for _, _, s in results if s == "ok")
    miss = sum(1 for _, _, s in results if s.startswith("missing"))
    err = [r for r in results if r[2].startswith("error")]
    console.print(f"[green]ok={ok}[/green] missing_upstream={miss} "
                  f"errors={len(err)} in {time.time()-t0:.1f}s "
                  f"({len(missing)} docs requested)")
    if err:
        for d, f, s in err[:10]:
            console.print(f"  [red]ERR[/red] {d}.{f}: {s}")
        raise typer.Exit(code=1)


@app.command()
def scan(mirror_path: Optional[Path] = typer.Option(
        None, exists=True, file_okay=False,
        help="rsync'd mirror root (default: <home>/mirror)")):
    """Register files from an rsync-produced mirror into the DB (post-rsync bootstrap)."""
    paths = _paths()
    conn = _db(paths)
    root = Path(mirror_path) if mirror_path else paths.mirror
    stats = scanner.scan_mirror(conn, root)
    console.print(f"scan of {root}: {json.dumps(stats)}")


@app.command()
def status():
    """What the library holds and which tier it is at."""
    from . import library
    _legacy_hint()
    paths = _paths()
    conn = _db(paths)
    st = library.state(conn)
    stats = db_stats(conn)
    table = Table(title=f"rfclib @ {paths.home}")
    table.add_column("key", style="cyan")
    table.add_column("value")
    if not st["docs"]:
        table.add_row("state", "[yellow]empty: run `rfclib init`[/yellow]")
    table.add_row("network", f"{st['network']} (RFCLIB_NETWORK)")
    feats = library.features()
    table.add_row("optional features", "  ".join(
        f"{k}: {'yes' if v else 'no'}" for k, v in feats.items())
        + ("" if all(feats.values()) else
           escape("  (pip install 'rfclib[mcp,semantic]')")))
    table.add_row("documents (catalog)",
                  f"{st['docs']:,} ({st['rfcs']:,} RFCs, "
                  f"{st['current_rfcs']:,} current)")
    table.add_row("catalog synced", str(st["manifest_synced_at"]))
    table.add_row("errata", f"{st['errata']:,} (synced "
                            f"{st['errata_synced_at'] or 'never'})")
    table.add_row("subjects", f"{st['subjects']} (synced "
                              f"{st['subjects_synced_at'] or 'never'})")
    table.add_row("local files", json.dumps(stats["files_by_fmt"]))
    table.add_row("local bytes", f"{stats['files_bytes']:,}")
    table.add_row("section-indexed",
                  f"{st['indexed']:,} docs ({st['indexed_current']:,} of "
                  f"{st['current_rfcs']:,} current RFCs)")
    table.add_row("embedded sections", f"{st['embedded_chunks']:,}")
    from .index import embed as ix_embed
    table.add_row("embedding model",
                  "in library" if (ix_embed.model_dir() / "config.json")
                  .is_file() else "not downloaded")
    table.add_row("newest pub_date", str(stats["newest_pub_date"]))
    console.print(table)


@app.command()
def search(query: str, limit: int = 10, include_obsolete: bool = False,
           body: bool = typer.Option(
               False, "--body", "-b",
               help="full-text search INSIDE documents (needs `rfclib index build`)")):
    """Search titles/abstracts/keywords; --body searches section-level full text."""
    paths = _paths()
    conn = _db(paths)
    if body:
        for h in ix_search.search_chunks(conn, query, limit=limit,
                                         include_obsolete=include_obsolete):
            sec = f" §{h['sec_num']}" if h["sec_num"] else ""
            console.print(f"[bold]{h['doc_id']}[/bold]{sec} "
                          f"{escape(h['sec_title'])} "
                          f"[dim](lines {h['start_line']}-{h['end_line']})[/dim]")
            console.print(f"    {escape(h['snippet'])}")
        return
    for h in q.search(conn, query, limit=limit, include_obsolete=include_obsolete):
        flag = "" if h["is_current"] else " [red](obsolete)[/red]"
        console.print(f"[bold]{h['doc_id']}[/bold] {h['pub_date']} "
                      f"[{h['current_status']}] " + escape(str(h["title"])) + flag)


@app.command("vsearch")
def vsearch(query: str, limit: int = 10, include_obsolete: bool = False):
    """Semantic (embedding) search inside documents (needs `rfclib index embed`)."""
    conn = _db(_paths())
    try:
        hits = ix_embed.semantic_search(conn, query, limit=limit,
                                        include_obsolete=include_obsolete)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    for h in hits:
        sec = f" §{h['sec_num']}" if h["sec_num"] else ""
        console.print(f"[bold]{h['doc_id']}[/bold]{sec} "
                      f"{escape(h['sec_title'])} "
                      f"[dim](lines {h['start_line']}-{h['end_line']}, "
                      f"d={h['distance']:.3f})[/dim]")
        console.print(f"    {escape(h['preview'])[:200]}")


@app.command("hsearch")
def hsearch(query: str, limit: int = 10, include_obsolete: bool = False):
    """Hybrid retrieval: BM25 + embeddings fused (RRF) with status prior.

    Recommended default for open questions: exact-term hits from FTS5 are
    merged with concept hits from the vector index; standards-track and
    BCP/STD documents get a ranking boost. Shows which list(s) backed each
    hit (bm25+knn+title = all three agree; title = doc's own title matched).
    """
    conn = _db(_paths())
    try:
        hits = ix_hybrid.hybrid_search(conn, query, limit=limit,
                                       include_obsolete=include_obsolete)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    if not hits:
        console.print("[yellow]no hits[/yellow]")
        return
    for h in hits:
        sec = f" §{h['sec_num']}" if h["sec_num"] else ""
        console.print(
            f"[bold]{h['doc_id']}[/bold]{sec} {escape(h['sec_title'])} "
            f"[dim](lines {h['start_line']}-{h['end_line']}, "
            f"rrf={h['rrf']:.4f}, {h['sources']})[/dim]")
        console.print(f"    {escape(h['snippet'])[:200]}")


@app.command()
def get(doc_id: str, fmt: str = "txt", lines: int = 40, start_line: int = 1):
    """Print a document (first lines by default)."""
    paths = _paths()
    conn = _db(paths)
    try:
        doc = q.get_document(conn, _did(doc_id), fmt=fmt,
                             mirror_root=paths.mirror, start_line=start_line,
                             max_lines=lines)
    except q.NotFound:
        console.print(f"[red]{doc_id} not found[/red] — run "
                      "`rfclib manifest --refresh` if it is very new.")
        raise typer.Exit(code=1)
    if doc.get("content") is None:
        console.print(f"[yellow]{doc.get('note') or doc.get('metadata')}[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"# {doc['doc_id']} via {doc['path']} (lines "
                  f"{doc['start_line']}-{doc['end_line']} of {doc['total_lines']})")
    console.print(doc["content"], markup=False, highlight=False)


@app.command()
def meta(doc_id: str):
    """Full metadata + relations as JSON."""
    paths = _paths()
    conn = _db(paths)
    try:
        console.print_json(json.dumps(
            q.get_metadata(conn, _did(doc_id)), default=str))
    except q.NotFound:
        console.print(f"[red]{doc_id} not found[/red]")
        raise typer.Exit(code=1)


@app.command()
def rels(doc_id: str):
    """Show the relation graph for a document."""
    paths = _paths()
    conn = _db(paths)
    try:
        m = q.get_metadata(conn, _did(doc_id))
    except q.NotFound:
        console.print(f"[red]{doc_id} not found[/red]")
        raise typer.Exit(code=1)
    if not m["relations"]:
        console.print("no relations")
    for kind, targets in sorted(m["relations"].items()):
        console.print(f"  {kind}: {', '.join(targets)}")


@app.command()
def refs(doc_id: Optional[str] = typer.Argument(
            None, help="document to inspect; omit when using --build"),
         build: bool = typer.Option(
            False, "--build",
            help="mine the citation graph from local txt files "
                 "(incremental by content hash)"),
         force: bool = typer.Option(False, "--force",
                                    help="re-mine unchanged docs too"),
         limit: int = typer.Option(40, help="peers shown per direction")):
    """Citation graph: what an RFC cites, and what cites it.

    Includes normative/informative tags from References sections and
    section-level anchors mined from 'Section N.M of [RFCX]' phrasing.
    """
    conn = _db(_paths())
    if build:
        t0 = time.time()
        res = graph.build(conn, force=force)
        console.print(f"mined {res['built']} docs ({res['new_edges']} new "
                      f"edges), {res['skipped_unchanged']} unchanged; "
                      f"{res['total_edges']} total edges "
                      f"in {time.time() - t0:.0f}s")
        if doc_id is None:
            raise typer.Exit(code=0)
    if doc_id is None:
        console.print("[yellow]pass a DOC_ID or --build[/yellow]")
        raise typer.Exit(code=2)
    did = _did(doc_id)
    r = graph.get_refs(conn, did, limit=limit)
    if not r["built"]:
        console.print("[yellow]citation graph is empty; run "
                      "`rfclib refs --build` first[/yellow]")
        raise typer.Exit(code=1)

    def show(rows: list[dict], label: str):
        console.print(f"[bold]{label} ({len(rows)})[/bold]")
        for e in rows:
            secs = (" §" + ", §".join(e["sections"])) if e["sections"] else ""
            obsolete = "" if e["is_current"] else " [red](obs)[/red]"
            console.print(
                f"  [cyan]{e['doc_id']:<10}[/cyan]"
                f"[dim]{'+'.join(e['kinds'])}[/dim]"
                f"[magenta]{secs[:44]}[/magenta]"
                f" {escape((e['title'] or '')[:56])}{obsolete}")

    show(r["outbound"], f"{did} cites")
    console.print()
    show(r["inbound"], f"cited by {did}")


@app.command()
def errata(doc_id: str = typer.Argument(
               "", help="document id; omit with --sync-all"),
           refresh: bool = typer.Option(
               False, "--refresh", help="re-fetch from the errata service"),
           all_statuses: bool = typer.Option(
               False, "--all",
               help="also show Reported/Held/Rejected, not just Verified"),
           sync_all: bool = typer.Option(
               False, "--sync-all",
               help="load every erratum from the RFC Editor bulk API "
                    "(~12 MB, one request)")):
    """Verified-errata overlay from the RFC Editor errata service.

    --sync-all loads the bulk feed once so every document's errata status
    is known offline; otherwise fetches on demand (one polite request per
    document) and caches locally.
    """
    conn = _db(_paths())
    if sync_all:
        console.print(json.dumps(errata_mod.sync_bulk(conn)))
        return
    if not doc_id:
        raise typer.BadParameter("give a document id, or --sync-all")
    did = q.resolve(conn, _did(doc_id))
    try:
        res = errata_mod.ensure(conn, did, refresh=refresh)
    except Exception as e:  # noqa: BLE001 - network layer errors vary
        console.print(f"[red]errata fetch failed:[/red] {escape(str(e))}")
        raise typer.Exit(code=1)
    rows = res["results"]
    verified = [e for e in rows if e["status"] == "Verified"]
    other = [e for e in rows if e["status"] != "Verified"]
    console.print(f"[bold]{did}[/bold]: {len(verified)} verified errata "
                  f"({len(other)} other status) "
                  f"[dim]source={res['source']}"
                  f"{', fetched ' + res['fetched_at'] if res.get('fetched_at') else ''}[/dim]")

    def show(entries: list[dict], label: str):
        if not entries:
            return
        console.print(f"[bold]{label}[/bold]")
        for e in entries:
            sec = f" §{e['section']}" if e["section"] else ""
            excerpt = ((e["should_say"] or e["says"] or e["notes"]
                        or "").splitlines() or [""])[0]
            console.print(
                f"  [cyan]eid {e['eid']}[/cyan] [dim]{e['status']} · "
                f"{e['type'] or '?'}[/dim][magenta]{sec}[/magenta] "
                f"{escape(excerpt[:70])}")

    show(verified, "Verified")
    if all_statuses:
        show(other, "Other statuses")


@app.command("resolve")
def resolve_cmd(doc_id: str):
    """Resolve a BCP/STD/FYI alias to its content-bearing RFC."""
    paths = _paths()
    conn = _db(paths)
    did = _did(doc_id)
    try:
        target = q.resolve(conn, did)
    except q.NotFound:
        console.print(f"[red]{did} not found[/red]")
        raise typer.Exit(code=1)
    console.print(f"{did} -> {target}")


@app.command()
def toc(doc_id: str):
    """Section outline with exact line ranges (use with `get --start_line`)."""
    conn = _db(_paths())
    did = _did(doc_id)
    rows = ix_search.get_toc(conn, did)
    if not rows:
        console.print(f"[yellow]no chunks for {did}; "
                      "run `rfclib index build`[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"[bold]{did}[/bold] outline:")
    for r in rows:
        console.print(f"  [cyan]{r['sec_num'] or '-':<12}[/cyan]"
                      f"{escape(r['sec_title'])[:60]:<62}"
                      f"[dim]lines {r['start_line']}-{r['end_line']}[/dim]")


@app.command("index")
def index_cmd(action: str = typer.Argument("status", help="build | embed | status"),
              limit: int = typer.Option(0, help="max chunks to embed (0 = all)"),
              model: str = typer.Option("minishlab/potion-base-8M", "--model",
                                        help="model2vec model id for embed")):
    """Maintain retrieval indexes: build=FTS chunks, embed=vectors."""
    paths = _paths()
    conn = _db(paths)
    t0 = time.time()
    lock = (_locked(paths) if action in ("build", "embed")
            else contextlib.nullcontext())
    with lock:
        try:
            st = _index_action(action, conn, paths, model, limit)
        except RuntimeError as e:     # e.g. rfclib[semantic] not installed
            console.print(f"[red]{escape(str(e))}[/red]")
            raise typer.Exit(code=1)
    st["seconds"] = round(time.time() - t0, 1)
    console.print(json.dumps(st))


def _index_action(action: str, conn, paths: Paths, model: str,
                  limit: int) -> dict:
    if action == "build":
        st = ix_search.build_chunks(
            conn, paths.mirror,
            progress=lambda d, t: console.print(
                f"  chunked {d}/{t} docs", end="\r", highlight=False))
        console.print()
    elif action == "embed":
        st = ix_embed.embed_pending(
            conn, model_name=model, limit=limit,
            progress=lambda d, t: console.print(
                f"  embedded {d}/{t} chunks", end="\r", highlight=False))
        console.print()
    else:
        st = ix_search.index_stats(conn)
    return st


MCP_HTTP_PORT = 8765
_LOOPBACK = ("127.0.0.1", "localhost", "::1")


@app.command()
def mcp(
    transport: str = typer.Option(
        "stdio", "--transport",
        help="stdio: one server per client (default). http: one shared "
             "server for every client (MCP streamable HTTP at /mcp)."),
    host: str = typer.Option(
        "127.0.0.1", "--host",
        help="http: address to bind. There is no authentication: keep it "
             "on loopback, or put an authenticating reverse proxy in front."),
    port: int = typer.Option(MCP_HTTP_PORT, "--port", help="http: TCP port."),
    allowed_host: list[str] = typer.Option(
        None, "--allowed-host",
        help="http, with a non-loopback --host: a Host header value to "
             "accept, e.g. 'localhost:*' or 'rfc.example.net'. Repeatable. "
             "Without it the Host/Origin check is off."),
    read_only: bool = typer.Option(
        False, "--read-only",
        help="Never write the library: open the database read-only and "
             "never fetch (same as RFCLIB_READONLY=1). For extra stdio "
             "servers beside a shared http server."),
):
    """Run the MCP server: on stdio for one client, or as one shared HTTP
    server (--transport http) that every client connects to by URL."""
    import logging
    import os
    transport = transport.strip().lower()
    if transport in ("streamable-http", "streamable_http"):
        transport = "http"
    if transport not in ("stdio", "http"):
        Console(stderr=True).print(
            f"[red]unknown --transport {escape(transport)}: use stdio or "
            "http[/red]")
        raise typer.Exit(code=2)
    if read_only:
        os.environ["RFCLIB_READONLY"] = "1"
    # stdout is the JSON-RPC channel; stderr is the client's log. Per-request
    # HTTP lines from httpx/huggingface_hub would flood it.
    for name in ("httpx", "httpcore", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        from .mcp.server import mcp as mcp_server
    except ImportError as e:
        if "mcp" not in str(e).lower():
            raise
        # stderr: stdout is the JSON-RPC channel the client is reading
        # escape(): rich would read "[mcp,semantic]" as a markup tag
        Console(stderr=True).print(
            "[red]The MCP server is an optional feature and is not "
            "installed.[/red]\n" + escape(
                "  pip install 'rfclib[mcp,semantic]'\n"
                "  or run it with: uvx --from 'rfclib[mcp,semantic]' "
                "rfclib mcp"), highlight=False)
        raise typer.Exit(code=2)
    from primarysource import serve
    if transport == "http":
        Console(stderr=True).print(
            f"rfclib mcp: http://{host}:{port}/mcp  (library "
            f"{escape(str(Paths.default().home))}"
            f"{', read-only' if read_only else ''})", highlight=False)
    serve.run(mcp_server, transport, host=host, port=port,
              allowed_hosts=allowed_host or ())


subjects_app = typer.Typer(
    help="RFC Editor subject taxonomy (rfc-editor.org/subjects): "
         "browse the collection by curated topic tree.")
app.add_typer(subjects_app, name="subjects")


@subjects_app.command("sync")
def subjects_sync(
        force: bool = typer.Option(
            False, "--force", help="re-download the subject pages"),
        limit: int = typer.Option(
            0, "--limit", help="crawl only the first N subjects (smoke run)"),
        delay: float = typer.Option(
            0.1, help="polite inter-request delay, seconds"),
):
    """Mirror the subject tree and per-subject document lists (~640 pages)."""
    from . import subjects as subj_mod
    paths = _paths()
    conn = _db(paths)
    t0 = time.time()
    res = subj_mod.sync(
        conn, paths, force=force, delay=delay, limit=limit,
        progress=lambda m: console.print(f"  {m}", highlight=False))
    console.print(
        f"[green]subjects synced[/green]: {res['subjects']} subjects, "
        f"{res['assignments']} assignments over {res['distinct_docs']} docs "
        f"({time.time() - t0:.1f}s)")
    if res["failed"]:
        console.print(f"[yellow]failed pages ({len(res['failed'])}):[/yellow] "
                      + ", ".join(res["failed"][:10]))


@subjects_app.command("list")
def subjects_list(
        contains: Optional[str] = typer.Argument(
            None, help="substring filter on slug/name/description"),
        descriptions: bool = typer.Option(
            False, "--descriptions", help="show the RFC Editor blurbs"),
):
    """Show the subject tree (or a filtered slice), parents before children."""
    from . import subjects as subj_mod
    conn = _db(_paths())
    if not subj_mod.subjects_ready(conn):
        console.print("[red]taxonomy not synced; run `rfclib subjects sync`[/red]")
        raise typer.Exit(code=1)
    rows = subj_mod.list_subjects(conn, contains=contains)
    for r in rows:
        line = ("  " * r["depth"] + "[dim]" + "  " * r["depth"]
                + escape(r["slug"]) + f"[/dim] {escape(r['name'])}"
                + f" [cyan]{r['doc_count'] if r['doc_count'] is not None else '?'}[/cyan]")
        console.print(line, highlight=False)
        if descriptions and r["description"]:
            console.print("      " * (r["depth"] + 1)
                          + f"[dim]{escape(r['description'])}[/dim]",
                          highlight=False)
    console.print(f"[bold]{len(rows)} subjects[/bold]")


@subjects_app.command("get")
def subjects_get(
        name: str = typer.Argument(..., help="subject slug or name, e.g. quic"),
        limit: int = typer.Option(40, help="max docs to show"),
        include_obsolete: bool = typer.Option(False),
):
    """List the documents inside one subject (incl. descendants), newest first."""
    from . import subjects as subj_mod
    conn = _db(_paths())
    try:
        data = subj_mod.get_subject(conn, name,
                                    include_obsolete=include_obsolete,
                                    limit=limit)
    except subj_mod.SubjectNotFound as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(code=1)
    s = data["subject"]
    console.print(f"[bold]{escape(s['name'])}[/bold] ({s['slug']})"
                  + (f" - {escape(s['description'])}" if s["description"] else ""))
    if data["children"]:
        console.print("[dim]children:[/dim] " + ", ".join(
            f"{c['slug']} ({c['doc_count']})" for c in data["children"]))
    for d in data["docs"]:
        console.print(
            f"  {d['doc_id']:<9} {(d['pub_date'] or '-'):<10} "
            f"{(d['current_status'] or '')[:18]:<18} {escape(d['title'] or '')}",
            highlight=False)
    extra = f", next offset {data['next_offset']}" if data["next_offset"] else ""
    console.print(f"{len(data['docs'])} shown of {data['docs_total']} docs{extra}")


packs_app = typer.Typer(help="Build & serve curated RFC content packs (.rfcpack).")
app.add_typer(packs_app, name="packs")


def _collection_dirs(collections_dir: Optional[Path]) -> list[Path]:
    dirs = []
    if collections_dir:
        dirs.append(Path(collections_dir))
    dirs.append(_paths().home / "collections")
    return dirs


@packs_app.command("list")
def packs_list(collections_dir: Optional[Path] = typer.Option(
        None, "--collections-dir", exists=True, file_okay=False,
        help="extra dir with user <id>.json collection manifests")):
    """Show available collections and how many docs each resolves to."""
    conn = _db(_paths())
    for coll in pack_collections.list_collections(_collection_dirs(collections_dir)):
        ids = pack_collections.resolve(conn, coll)
        console.print(f"[bold]{coll.id:<20}[/bold] {len(ids):>5} docs  "
                      f"{escape(coll.name)}")


@packs_app.command("build")
def packs_build(
        names: list[str] = typer.Argument(None, help="collection ids"),
        all_collections: bool = typer.Option(
            False, "--all", help="build every listed collection"),
        formats: str = typer.Option(
            "txt", help="comma-separated formats: txt,html (txt enables search)"),
        search: bool = typer.Option(
            True, "--search/--no-search",
            help="embed an offline FTS5 search index (search.sqlite)"),
        out: Path = typer.Option(
            Path("export-packs"), "--out", file_okay=False,
            help="output dir for .rfcpack files + catalog.json"),
        collections_dir: Optional[Path] = typer.Option(
            None, "--collections-dir", exists=True, file_okay=False),
):
    """Build .rfcpack files for one or more collections."""
    conn = _db(_paths())
    dirs = _collection_dirs(collections_dir)
    if all_collections:
        names = [c.id for c in pack_collections.list_collections(dirs)]
    if not names:
        console.print("[red]give collection ids or --all[/red]")
        raise typer.Exit(code=2)
    fmts = [f.strip() for f in formats.split(",") if f.strip()]
    t0 = time.time()
    results = []
    for name in names:
        path = pack_collections.find_collection(name, dirs)
        coll = pack_collections.Collection.from_json(
            json.loads(path.read_text("utf-8")), fallback_id=path.stem)
        try:
            res = pack_builder.build_pack(
                conn, coll, out, formats=fmts, search=search,
                progress=lambda m: console.print(f"  {coll.id}: {m}",
                                                 highlight=False))
        except pack_builder.MissingFiles as e:
            console.print(f"[red]{coll.id}: {e}[/red]")
            raise typer.Exit(code=1)
        console.print(
            f"[green]{coll.id}[/green]: {res['docs']} docs, "
            f"{res['chunks']} chunks, {res['bytes'] / 1e6:.1f} MB "
            f"-> {res['path']}")
        results.append(res)
    cat = pack_serve.write_catalog(out)
    console.print(f"catalog: {len(cat['packs'])} packs in {out} "
                  f"({time.time() - t0:.1f}s)")


@packs_app.command("export")
def packs_export(
        names: list[str] = typer.Argument(None, help="collection ids"),
        all_collections: bool = typer.Option(
            False, "--all", help="export every listed collection"),
        formats: str = typer.Option(
            "epub,html", help="comma list of: epub, html, zim, docset"),
        out: Path = typer.Option(
            Path("export-formats"), "--out", file_okay=False,
            help="output dir for .epub/.zim files / html mirrors"),
        link_refs: str = typer.Option(
            "internal", help="link 'RFC 9000' refs: none|internal|external"),
        collections_dir: Optional[Path] = typer.Option(
            None, "--collections-dir", exists=True, file_okay=False),
):
    """Export collections for third-party readers (EPUB, HTML mirror, ZIM, docset).

    The zim format needs the optional native bindings (`uv sync --extra
    zim`); epub/html/docset are pure stdlib. The .rfcpack format stays
    the native one for this app's own Android reader (`packs build`).
    """
    fmts = [f.strip().lower() for f in formats.split(",") if f.strip()]
    bad = [f for f in fmts if f not in ("epub", "html", "zim", "docset")]
    if bad:
        console.print(f"[red]unknown format(s): {', '.join(bad)} "
                      "(available: epub, html, zim, docset)[/red]")
        raise typer.Exit(code=2)
    if link_refs not in ("none", "internal", "external"):
        console.print("[red]--link-refs must be none|internal|external[/red]")
        raise typer.Exit(code=2)
    pack_zim = None
    if "zim" in fmts:
        from .packs import zimexport as pack_zim
        if not pack_zim.HAVE_LIBZIM:
            console.print("[red]zim format needs the optional native "
                          "bindings: uv sync --extra zim[/red]")
            raise typer.Exit(code=2)
    conn = _db(_paths())
    dirs = _collection_dirs(collections_dir)
    if all_collections:
        names = [c.id for c in pack_collections.list_collections(dirs)]
    if not names:
        console.print("[red]give collection ids or --all[/red]")
        raise typer.Exit(code=2)
    t0 = time.time()
    for name in names:
        path = pack_collections.find_collection(name, dirs)
        coll = pack_collections.Collection.from_json(
            json.loads(path.read_text("utf-8")), fallback_id=path.stem)
        say = lambda m, cid=coll.id: console.print(  # noqa: E731
            f"  {cid}: {m}", highlight=False)
        try:
            docs = pack_export.iter_export_docs(conn, coll, progress=say)
        except pack_export.MissingFiles as e:
            console.print(f"[red]{coll.id}: {e}[/red]")
            raise typer.Exit(code=1)
        for fmt in fmts:
            builder = (pack_epub.build_epub if fmt == "epub"
                       else pack_html.build_html if fmt == "html"
                       else pack_docset.build_docset if fmt == "docset"
                       else pack_zim.build_zim)
            res = builder(coll, docs, out, link_refs=link_refs, progress=say)
            console.print(
                f"[green]{coll.id}[/green] {fmt}: {res['docs']} docs, "
                f"{res['bytes'] / 1e6:.1f} MB -> {res['path']}")
    console.print(f"done in {time.time() - t0:.1f}s")


@packs_app.command("catalog")
def packs_catalog(out: Path = typer.Option(
        Path("export-packs"), "--out", file_okay=False,
        help="dir containing .rfcpack files")):
    """(Re)build catalog.json with sha256/size for every pack in a dir."""
    cat = pack_serve.write_catalog(out)
    for p in cat["packs"]:
        console.print(f"  {p['id']:<20} {p['doc_count']:>5} docs  "
                      f"{p['size'] / 1e6:>9.1f} MB  {p['sha256'][:16]}…")


@packs_app.command("serve")
def packs_serve_cmd(out: Path = typer.Option(
        Path("export-packs"), "--dir", exists=True, file_okay=False,
        help="dir with .rfcpack files + catalog.json"),
        host: str = typer.Option("0.0.0.0", help="bind address"),
        port: int = typer.Option(8100, help="TCP port")):
    """Serve packs over LAN HTTP for the Android reader (Sync feature)."""
    httpd = pack_serve.serve(out, host, port)
    console.print(f"serving [bold]{out}[/bold] on "
                  f"[cyan]http://{host or '0.0.0.0'}:{port}[/cyan] "
                  "(Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("stopped")


def main(argv=None):
    import sys
    try:
        # Windows consoles default to a legacy code page: '§' and '¶' in
        # refs would print as '?'. MCP stdio is JSON-RPC in UTF-8 either way.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if argv is None:
        app()
    else:
        app(args=list(argv), prog_name="primarysource rfc")


if __name__ == "__main__":
    main()

