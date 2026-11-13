"""zimlore: a Kiwix library (ZIM files) as token-budgeted, citable documentation.

    zimlore info                      where the library is, what is installed, whether libzim is available
    zimlore list [name]               installed libraries (or those matching a name), with edition dates
    zimlore resolve flask             the one library a name means, or the candidates when it is ambiguous
    zimlore search "blueprint" -l flask   search one library; without -l, search every library
    zimlore read flask§blueprints/index#why-blueprints
    zimlore outline python§library/os ; zimlore outline python --prefix library/a
    zimlore links flask§blueprints/index ; zimlore cite flask§blueprints/index
    zimlore catalog flask             search the public Kiwix catalogue (network)
    zimlore catalog --refresh         store the catalogue as an offline snapshot (network)
    zimlore catalog --offline [flask] read the snapshot; ranks like `available` (no network)
    zimlore available flask           what could be installed, from the snapshot (no network)
    zimlore get devdocs_en_flask [--replace]   download a ZIM, verified by SHA-256 (network)
    zimlore outdated                  installed ZIMs with a newer edition in the catalogue (network)
    zimlore add PATH [--link] [--force]   install a local ZIM, checked by libzim, with a provenance sidecar
    zimlore sync [--manifest F] [--group G ...] [--dry-run] [--update]   make the library match a manifest (network)
    zimlore verify [name] [--adopt]   check files against their provenance sidecar and libzim's checksum
    zimlore remove NAME [--edition D | --all] [--yes]   delete editions (dry run without --yes)
    zimlore prune [--keep N] [--include-unmanaged] [--yes]   drop old editions (dry run without --yes)
    zimlore du                        disk use per library
    zimlore mcp                       serve the tools over stdio (needs the mcp extra)

A reference is `library§path[#anchor][¶n]`; `::` is the ASCII spelling of `§`. Every command takes `--json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__, _libzim, catalog, groups, library, manage, service, snapshot, sync
from .errors import ZimloreError


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _emit(args: argparse.Namespace, data: dict[str, Any], human: Callable[[dict[str, Any]], None]) -> int:
    if args.json:
        _print_json(data)
    else:
        human(data)
    return 0


def _fmt_freshness(row: dict[str, Any]) -> str:
    fresh = row["freshness"]
    if fresh["age_days"] is None:
        return "undated"
    return f"{fresh['date']} ({fresh['age_days']} days old{', STALE' if fresh['stale'] else ''})"


def cmd_info(args: argparse.Namespace) -> int:
    scanned = library.scan()
    data = {
        "version": __version__,
        "home": str(library.home()),
        "zim_directories": [str(d) for d in scanned.directories],
        "libzim": _libzim.available(),
        "installed": len(scanned.books),
        "problems": scanned.problems,
    }

    def human(d: dict[str, Any]) -> None:
        print(f"zimlore {d['version']}\nhome: {d['home']}\nZIM directories: {', '.join(d['zim_directories'])}")
        print(f"libzim: {'available' if d['libzim'] else 'MISSING - ' + _libzim.REMEDY}")
        print(f"installed: {d['installed']}")
        for problem in d["problems"]:
            print(f"  unreadable: {problem['path']}: {problem['error']}")

    return _emit(args, data, human)


def cmd_list(args: argparse.Namespace) -> int:
    data = service.libraries(args.name or "", args.limit, args.verbose, args.all_versions)

    def human(d: dict[str, Any]) -> None:
        for row in d["libraries"]:
            size = row["size_bytes"] / 1e6
            label = f"{row['family']} [{', '.join(row['versions'])}]" if "versions" in row else row["name"]
            print(f"{label}  {row['title']}  [{row['search']}; {size:.1f} MB; {_fmt_freshness(row)}]")
            if "match" in row:
                print(f"    {row['match']}")
        if not d["libraries"]:
            print(f"no installed library matches {d.get('query')!r}")
        for problem in d.get("problems", []):
            print(f"unreadable: {problem['path']}: {problem['error']}")
        if d.get("truncated"):
            print(f"({len(d['libraries'])} of {d['total']} shown; --limit shows more)")

    return _emit(args, data, human)


def cmd_resolve(args: argparse.Namespace) -> int:
    def human(d: dict[str, Any]) -> None:
        print(f"{d['name']}  {d['title']}\n  edition: {_fmt_freshness(d)}\n  match: {d['match']}")
        print(f"  search: {d['search']}; license: {d['license'] or 'not stated in the ZIM'}")
        if "upstream" in d["version"]:
            others = f"; also installed: {', '.join(d['other_versions'])}" if d.get("other_versions") else ""
            print(f"  version: {d['version']['upstream']} ({d['version']['selected']}){others}")

    return _emit(args, service.resolve(args.name), human)


def cmd_search(args: argparse.Namespace) -> int:
    data = service.search(args.query, args.library, args.limit, args.max_tokens, args.language)

    def human(d: dict[str, Any]) -> None:
        for hit in d["hits"]:
            print(f"{hit['ref']}  {hit['title']}  [{hit['match']}]\n    {hit['excerpt']}")
        for key in ("title_only", "note", "ranking"):
            if key in d:
                print(f"({d[key]})")

    return _emit(args, data, human)


def cmd_read(args: argparse.Namespace) -> int:
    data = service.read(args.ref, args.library, args.start, args.max_tokens, args.format)

    def human(d: dict[str, Any]) -> None:
        print(d["content"])
        print(f"\n-- {d['cite']}")
        print(f"-- {_fmt_freshness(d)}; blocks {d['blocks']['from']}-{d['blocks']['to']} of {d['blocks']['of']}")
        if d["next"]:
            print(f"-- next: zimlore read '{d['next']['ref']}' --start {d['next']['start']}")

    return _emit(args, data, human)


def cmd_outline(args: argparse.Namespace) -> int:
    data = service.outline(args.ref, args.library, args.start, args.limit, args.prefix)

    def human(d: dict[str, Any]) -> None:
        for row in d.get("outline", []):
            indent = "  " * ((row.get("level") or 4) - 1)
            where = d["ref"] + ("#" + row["anchor"] if row.get("anchor") else "")
            print(f"{indent}{row['text']}  {where}")
        for row in d.get("entries", []):
            print(f"{row['title']}  {row['ref']}")
        if "next" in d:
            print(f"-- more: --start {d['next']['start']}")

    return _emit(args, data, human)


def cmd_links(args: argparse.Namespace) -> int:
    data = service.links(args.ref, args.library, args.limit)

    def human(d: dict[str, Any]) -> None:
        for row in d["links"]:
            target = row.get("url") or row["ref"] + ("" if row.get("in_zim") else "  (not in this ZIM)")
            print(f"{row['text']}  ->  {target}")

    return _emit(args, data, human)


def cmd_cite(args: argparse.Namespace) -> int:
    def human(d: dict[str, Any]) -> None:
        print(d["cite"])
        print(f"licence: {d['license']}")

    return _emit(args, service.cite(args.ref, args.library), human)


def _print_available(d: dict[str, Any]) -> None:
    snap = d["snapshot"]
    for row in d["available"]:
        state = f"INSTALLED {row['installed_edition']}" if row["installed"] else "not installed"
        print(
            f"{row['name']}  {row['title']}  [{row['date']}; ~{row['approx_mb']} MB; {row['articles']} articles; "
            f"{state}]\n    {row['install']}"
        )
    if not d["available"]:
        print(f"nothing in the snapshot matches {d['query']!r}")
    print(
        f"({len(d['available'])} shown of {d['matches']} matches; snapshot of {snap['fetched_at']}, "
        f"{snap['age_days']} days old, offline; zimlore catalog --refresh updates it)"
    )


def cmd_available(args: argparse.Namespace) -> int:
    return _emit(args, service.available(args.query, args.limit), _print_available)


def _catalog_refresh(args: argparse.Namespace) -> int:
    started = time.monotonic()
    data = snapshot.refresh(language=args.lang)
    data["seconds"] = round(time.monotonic() - started, 1)

    def human(d: dict[str, Any]) -> None:
        print(
            f"snapshot written: {d['entries']} entries of {d['total_results']} in {d['pages']} page(s), "
            f"{d['bytes'] / 1e6:.2f} MB, {d['seconds']} s -> {d['path']}"
        )

    return _emit(args, data, human)


def _catalog_offline(args: argparse.Namespace) -> int:
    if args.query:
        return _emit(args, service.available(args.query, args.count), _print_available)
    entries, fetched_at, age = snapshot.load()
    data = {"entries": len(entries), "fetched_at": fetched_at, "age_days": age, "path": str(snapshot.path())}

    def human(d: dict[str, Any]) -> None:
        print(f"snapshot: {d['entries']} entries, fetched {d['fetched_at']} ({d['age_days']} days old), {d['path']}")

    return _emit(args, data, human)


def cmd_catalog(args: argparse.Namespace) -> int:
    if args.refresh and args.offline:
        raise ZimloreError("--refresh uses the network and --offline forbids it; choose one")
    if args.refresh:
        return _catalog_refresh(args)
    if args.offline:
        return _catalog_offline(args)
    if not (args.query or args.tag):
        raise ZimloreError(
            "give a search query or --tag", "e.g. zimlore catalog flask ; zimlore catalog --tag devdocs"
        )
    entries, total = catalog.query(
        args.query or "",
        language=args.lang,
        count=args.count,
        tag=args.tag,
        max_bytes=int(args.max_mb * 1_000_000),
    )
    data = {
        "total": total,
        "entries": [
            {
                "name": e.name,
                "title": e.title,
                "date": e.date,
                "approx_mb": round(e.approx_bytes / 1e6, 1),
                "articles": e.articles,
                "summary": e.summary,
            }
            for e in catalog.latest(entries)
        ],
    }

    def human(d: dict[str, Any]) -> None:
        for row in d["entries"]:
            print(
                f"{row['name']}  {row['title']}  [{row['date']}; ~{row['approx_mb']} MB; {row['articles']} articles]"
            )
        print(f"({len(d['entries'])} shown of {d['total']} catalogue entries; zimlore get <name>)")

    return _emit(args, data, human)


def cmd_get(args: argparse.Namespace) -> int:
    found = catalog.latest(catalog.editions_of(args.name))
    if not found:
        raise ZimloreError(f"the catalogue has no ZIM named {args.name!r}", "zimlore catalog <words> finds names")
    entry = found[0]
    directory = library.zim_dirs()[0]
    print(f"{entry.name} {entry.date} (~{entry.approx_bytes / 1e6:.1f} MB) -> {directory}", file=sys.stderr)
    last = [0]

    def progress(done: int, total: int) -> None:
        if done - last[0] >= 5_000_000 or done == total:
            last[0] = done
            print(f"  {done / 1e6:.1f} / {total / 1e6:.1f} MB", file=sys.stderr)

    result = catalog.download_result(entry, directory, progress=progress, replace=args.replace)
    book = library.read_book(result.path)
    if result.status == "already-installed":
        print(f"already installed, identical to the catalogue's file (SHA-256 matches): {result.path}")
    else:
        verb = "replaced" if result.status == "replaced" else "installed"
        print(f"verified (SHA-256) and {verb}: {result.path}")
    print(f"licence: {service.licence_note(book)}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    data = manage.add_local(Path(args.path), link=args.link, force=args.force)

    def human(d: dict[str, Any]) -> None:
        if d["status"] == "already-installed":
            print(f"already installed (identical file): {d['file']}")
        else:
            how = {"copy": "copied", "hardlink": "hard-linked", "symlink": "symbolic-linked"}[d["mode"]]
            print(f"{how} and recorded (SHA-256 computed locally): {d['file']}")
            if d["forced"]:
                print("WARNING: libzim's checksum fails; installed because of --force. verify will flag it")
        print(f"licence: {service.licence_note(library.read_book(Path(d['file'])))}")

    return _emit(args, data, human)


def _print_plan(plan: sync.Plan) -> None:
    print(f"manifest: {plan.manifest or 'none (groups from the command line)'}")
    for item in plan.items:
        size = f"  ~{_mb(item.approx_bytes)}" if item.approx_bytes else ""
        have = f"  installed {item.installed}" if item.installed else ""
        age = "  OVER max_age_days" if item.over_max_age else ""
        note = f"  ({item.note})" if item.note else ""
        print(f"{item.action:11} {item.name}  catalogue {item.available or '-'}{have}{size}{age}{note}")
    for extra in plan.extras:
        print(f"extra       {extra['name']}  installed, not in the manifest; never removed by sync")
    print(
        f"to download: ~{_mb(plan.download_bytes)} "
        "(approximate, from the catalogue's rounded lengths; the .meta4 has the true size)"
    )
    if plan.budget is not None:
        verdict = "EXCEEDS the budget" if plan.over_budget else "within the budget"
        total = plan.installed_bytes + plan.download_bytes
        print(f"budget: {_mb(plan.budget)}; library after sync ~{_mb(total)}: {verdict}")


def cmd_sync(args: argparse.Namespace) -> int:
    path = sync.find_manifest(args.manifest)
    manifest = sync.load_manifest(path) if path else sync.Manifest()
    named = tuple(args.group or ())
    if not (manifest.libraries or manifest.groups or named):
        raise ZimloreError(
            "nothing to sync: " + (f"{path} names no libraries or groups" if path else "no manifest and no --group"),
            f"write ./{sync.MANIFEST_NAME} or {library.home() / sync.HOME_MANIFEST} "
            f'(libraries = ["devdocs_en_python"]), or run: zimlore sync --group {sorted(groups.GROUPS)[0]} --dry-run',
        )
    plan = sync.make_plan(manifest, named, update=args.update)
    results: list[dict[str, Any]] = []
    if args.json:
        if not args.dry_run:
            results = sync.execute(plan)
        _print_json({**plan.as_dict(), "dry_run": args.dry_run, "results": results})
    else:
        _print_plan(plan)
        if not args.dry_run:
            last: dict[str, int] = {}

            def progress(name: str, done: int, total: int) -> None:
                if done - last.get(name, 0) >= 5_000_000 or done == total:
                    last[name] = done
                    print(f"  {name}: {done / 1e6:.1f} / {total / 1e6:.1f} MB", file=sys.stderr)

            results = sync.execute(plan, progress=progress)
            for row in results:
                print(f"{'installed' if row['ok'] else 'FAILED'}  {row['name']}  {row.get('file') or row['error']}")
        else:
            print("dry run: nothing was downloaded or changed")
    failed = [r for r in results if not r["ok"]]
    return 1 if failed or plan.problems or (args.dry_run and plan.over_budget) else 0


def cmd_outdated(args: argparse.Namespace) -> int:
    scanned = library.scan()
    rows = []
    for name in sorted({b.name for b in scanned.books}):
        mine = library.newest([b for b in scanned.books if b.name == name])
        if mine is None:
            continue
        newest = catalog.latest(catalog.editions_of(name))
        rows.append(
            {
                "name": name,
                "installed": mine.date,
                "catalogue": newest[0].date if newest else None,
                "outdated": library.is_newer(newest[0].date, mine.date) if newest else False,
            }
        )

    def human(d: dict[str, Any]) -> None:
        for row in d["rows"]:
            state = (
                "NEWER AVAILABLE"
                if row["outdated"]
                else (
                    "not in catalogue"
                    if row["catalogue"] is None
                    else ("date unknown, cannot compare" if row["outdated"] is None else "current")
                )
            )
            print(f"{row['name']}  installed {row['installed']}  catalogue {row['catalogue']}  {state}")

    return _emit(args, {"rows": rows}, human)


def _mb(size: int) -> str:
    return f"{size / 1e6:.1f} MB"


def cmd_verify(args: argparse.Namespace) -> int:
    data = manage.verify(args.name or "", hash_files=not args.no_hash, adopt=args.adopt)

    def human(d: dict[str, Any]) -> None:
        for row in d["files"]:
            extra = row.get("why") or row.get("note") or row.get("provenance_problem") or ""
            print(f"{row['status']:10} {row['file']}  {extra}".rstrip())
        for problem in d["problems"]:
            print(f"unreadable {problem['path']}: {problem['error']}")
        unrecorded = sum(r["status"] == "unrecorded" for r in d["files"])
        if unrecorded:
            print(
                f"({unrecorded} file(s) have no provenance record; --adopt records what they are, not their origin)"
            )

    _emit(args, data, human)
    return 1 if data["failed"] else 0


def _report_deletion(data: dict[str, Any]) -> None:
    if data["applied"]:
        for item in data["deleted"]:
            gone = "  (already gone)" if item.get("already_gone") else ""
            print(f"deleted  {item['file']}  ({_mb(item['bytes'])}){gone}")
        for item in data["failed"]:
            print(f"FAILED   {item['file']}: {item['error']}")
            if item["hint"]:
                print(f"         fix: {item['hint']}")
    else:
        for item in data["files"]:
            print(f"would delete  {item['file']}  ({_mb(item['bytes'])})")
    for item in data["refused"]:
        print(f"REFUSED  {item['name']}: {item['reason']}")
        for path in item["files"]:
            print(f"         {path}")
    for item in data["skipped"]:
        print(f"kept     {item['file']}  ({item['reason']})")
    verb = "freed" if data["applied"] else "would free"
    print(f"{verb} {_mb(data['freed'] if data['applied'] else data['bytes'])}")
    if data["note"]:
        print(f"({data['note']})")


def _deletion_exit(data: dict[str, Any]) -> int:
    """1 when a file could not be deleted or a library was refused under --yes: partial work is never exit 0."""
    return 0 if data["ok"] else 1


def cmd_remove(args: argparse.Namespace) -> int:
    data = manage.remove(
        args.name, edition=args.edition, all_editions=args.all, all_versions=args.all_versions, apply=args.yes
    )
    _emit(args, data, _report_deletion)
    return _deletion_exit(data)


def cmd_prune(args: argparse.Namespace) -> int:
    data = manage.prune(keep=args.keep, apply=args.yes, include_unmanaged=args.include_unmanaged)
    _emit(args, data, _report_deletion)
    return _deletion_exit(data)


def cmd_du(args: argparse.Namespace) -> int:
    data = manage.du()

    def human(d: dict[str, Any]) -> None:
        for row in d["libraries"]:
            newest = row["newest"] or "undated"
            print(f"{_mb(row['bytes']):>10}  {row['name']}  ({row['editions']} edition(s), newest {newest})")
        print(f"{_mb(d['total_bytes']):>10}  total in {', '.join(d['directories'])}")
        if d["partial_bytes"]:
            print(f"{_mb(d['partial_bytes']):>10}  partial downloads (zimlore prune --yes removes them)")
        if d["free_bytes"] is not None:
            print(f"{_mb(d['free_bytes']):>10}  free on the volume")

    return _emit(args, data, human)


def cmd_mcp(_args: argparse.Namespace) -> int:
    from . import mcp

    try:
        mcp.require_extra()
    except ImportError as error:
        print(error, file=sys.stderr)
        return 2
    mcp.main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zimlore", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"zimlore {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Callable[[argparse.Namespace], int], help_text: str, json_flag: bool = True) -> Any:
        command = sub.add_parser(name, help=help_text, description=help_text)
        command.set_defaults(handler=handler)
        if json_flag:
            command.add_argument("--json", action="store_true", help="print the structured result")
        return command

    add("info", cmd_info, "where the library is and whether libzim is available")
    listing = add("list", cmd_list, "installed libraries, with edition dates")
    listing.add_argument("name", nargs="?")
    listing.add_argument("--limit", type=int, default=50, help="at most this many libraries (default 50)")
    listing.add_argument("--verbose", action="store_true", help="add description, creator, tags, licence, provenance")
    listing.add_argument("--all-versions", action="store_true", help="one row per ZIM Name instead of per package")
    add("resolve", cmd_resolve, "the one library a name means").add_argument("name")

    search = add("search", cmd_search, "search a library, or all libraries")
    search.add_argument("query")
    search.add_argument("--library", "-l", default="", help="restrict to one library (any alias); default: all")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--max-tokens", type=int, default=1500)
    search.add_argument(
        "--language", default="", help="'' ranks translations last, 'any' keeps engine order, 'ru' only that language"
    )

    read = add("read", cmd_read, "read an article, section (#anchor) or block (¶n), paged by token budget")
    read.add_argument("ref")
    read.add_argument("--library", default="", help="the library, when ref is a bare path")
    read.add_argument("--start", type=int, default=1, help="first block to return (the `next` cursor)")
    read.add_argument("--max-tokens", type=int, default=2000)
    read.add_argument("--format", choices=["markdown", "text"], default="markdown")

    outline = add("outline", cmd_outline, "headings of an article, or the articles of a library")
    outline.add_argument("ref")
    outline.add_argument("--library", default="")
    outline.add_argument("--start", type=int, default=0)
    outline.add_argument("--limit", type=int, default=100)
    outline.add_argument("--prefix", default="", help="only entries whose path starts with this")

    links = add("links", cmd_links, "links out of an article, resolved to refs")
    links.add_argument("ref")
    links.add_argument("--library", default="")
    links.add_argument("--limit", type=int, default=100)

    cite = add("cite", cmd_cite, "the citation string, edition and licence note for a ref")
    cite.add_argument("ref")
    cite.add_argument("--library", default="")

    catalogue = add("catalog", cmd_catalog, "search the public Kiwix catalogue (network)")
    catalogue.add_argument("query", nargs="?")
    catalogue.add_argument("--lang", default="eng", help="ISO 639-3 code, or '' for any")
    catalogue.add_argument("--count", type=int, default=20)
    catalogue.add_argument("--tag", default="", help="only ZIMs with this tag, e.g. devdocs or stackoverflow")
    catalogue.add_argument("--max-mb", type=float, default=0, help="only ZIMs of at most this many megabytes")
    catalogue.add_argument(
        "--refresh", action="store_true", help="fetch the whole catalogue into the offline snapshot"
    )
    catalogue.add_argument("--offline", action="store_true", help="read the snapshot; never touch the network")
    avail = add("available", cmd_available, "what could be installed, from the offline snapshot (no network)")
    avail.add_argument("query")
    avail.add_argument("--limit", type=int, default=8)

    get = add("get", cmd_get, "download a ZIM from the catalogue, verified by SHA-256 (network)")
    get.add_argument("name")
    get.add_argument(
        "--replace", action="store_true", help="replace an existing file of the same name (otherwise it is refused)"
    )
    add_cmd = add(
        "add", cmd_add, "install a local ZIM file into the library, checked first, with a provenance sidecar"
    )
    add_cmd.add_argument("path")
    add_cmd.add_argument("--link", action="store_true", help="hard-link (else symlink) instead of copying")
    add_cmd.add_argument("--force", action="store_true", help="install even though libzim's checksum fails")

    sync_cmd = add("sync", cmd_sync, "install the libraries a manifest names; never removes anything (network)")
    sync_cmd.add_argument(
        "--manifest", default="", help=f"default: ./{sync.MANIFEST_NAME}, then $ZIMLORE_HOME/libraries.toml"
    )
    sync_cmd.add_argument(
        "--group", nargs="+", action="extend", help=f"named sets: {', '.join(sorted(groups.GROUPS))}"
    )
    sync_cmd.add_argument("--dry-run", action="store_true", help="print the plan and sizes; download nothing")
    sync_cmd.add_argument("--update", action="store_true", help="also fetch newer editions, beside the installed one")
    add("outdated", cmd_outdated, "installed ZIMs that have a newer catalogue edition (network)")
    verify = add("verify", cmd_verify, "check installed files against their provenance and libzim's checksum")
    verify.add_argument("name", nargs="?")
    verify.add_argument("--no-hash", action="store_true", help="compare sizes only; do not recompute SHA-256")
    verify.add_argument("--adopt", action="store_true", help="record a provenance sidecar for files that lack one")

    remove = add("remove", cmd_remove, "delete installed editions of a library (dry run unless --yes)")
    remove.add_argument("name")
    remove.add_argument("--edition", default="", help="only this edition date")
    remove.add_argument("--all", action="store_true", help="every edition")
    remove.add_argument("--all-versions", action="store_true", help="every version of a package, all editions")
    remove.add_argument("--yes", action="store_true", help="actually delete")

    prune = add("prune", cmd_prune, "delete old editions and partial downloads (dry run unless --yes)")
    prune.add_argument("--keep", type=int, default=2, help="editions to keep per library (default 2)")
    prune.add_argument(
        "--include-unmanaged",
        action="store_true",
        help="also delete files zimlore did not install (no get/sync/add sidecar: a shared Kiwix library)",
    )
    prune.add_argument("--yes", action="store_true", help="actually delete")

    add("du", cmd_du, "disk use per library, partial downloads, free space")
    add("mcp", cmd_mcp, "serve the MCP tools over stdio (needs the mcp extra)", json_flag=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    # ZIM text is Unicode throughout (the reference grammar itself uses § and ¶), and a Windows console's code
    # page cannot print it: a documentation tool must not die on a curly quote.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except ZimloreError as error:
        if getattr(args, "json", False):
            _print_json(error.as_dict())
        else:
            print(error.message, file=sys.stderr)
            if error.hint:
                print(f"fix: {error.hint}", file=sys.stderr)
            for key in ("did_you_mean", "candidates", "installed", "anchors"):
                if key in error.extra:
                    print(f"{key}: {error.extra[key]}", file=sys.stderr)
        return 2
