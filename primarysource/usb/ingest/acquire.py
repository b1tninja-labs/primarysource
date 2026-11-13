"""Download the files named in the USB-IF catalogue, unpack ZIP packages, and record what was fetched.

Input: data/usb-catalog.json (from discover_usb). Output, under the data directory:
  raw/<slug>/<file>        each downloaded file as published
  raw/<slug>/pdf/<name>    PDFs taken from ZIP packages, with the ZIP kept beside them
  acquired.json            per file: url, path, size, sha256, and for ZIPs the member list

Only PDFs and ZIPs are kept. Each download goes to a .part file and is renamed only when complete.
Extraction is safe: members with absolute paths or ".." are refused, and only PDF members are written.
Requests are throttled to one per second. Pass --dry-run to print the plan and the total size first.
"""

from __future__ import annotations

from primarysource.usb.paths import PACKAGE_DATA

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

USER_AGENT = "usblib-acquire/0.1 (documentation corpus)"
DELAY = 1.0
CHUNK = 1 << 20


def _size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except urllib.error.URLError:
        return None
    finally:
        time.sleep(DELAY)


def _download(url: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, part.open("wb") as out:
        while chunk := resp.read(CHUNK):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    part.replace(dest)
    time.sleep(DELAY)
    return size, digest.hexdigest()


def _safe_member(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and name.lower().endswith(".pdf")


def _extract_pdfs(archive: Path, out_dir: Path) -> list[str]:
    written: list[str] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir() or not _safe_member(info.filename):
                continue
            target = out_dir / PurePosixPath(info.filename).name
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            written.append(target.name)
    return written


def plan(catalog: dict, only: set[str] | None) -> list[tuple[str, str, str]]:
    """(slug, url, filename) for every PDF or ZIP the catalogue names."""
    items = []
    for entry in catalog["entries"]:
        if only and entry["slug"] not in only:
            continue
        for url in entry["files"]:
            name = PurePosixPath(url).name
            items.append((entry["slug"], url, name))
    return items


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=PACKAGE_DATA / "usb-catalog.json")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--only", nargs="*", default=None, help="catalogue slugs to fetch (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    items = plan(catalog, set(args.only) if args.only else None)
    sizes = {url: _size(url) for _, url, _ in items} if args.dry_run else {}
    if args.dry_run:
        total = sum(s or 0 for s in sizes.values())
        for slug, url, name in items:
            print(f"{slug:<40} {sizes.get(url) or '?':>12}  {name}")
        print(f"{len(items)} files, {total / 1e9:.2f} GB known", file=sys.stderr)
        return 0
    manifest_path = args.data_dir / "acquired.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"schema": 1, "files": []}
    done = {f["url"] for f in manifest["files"]}
    for slug, url, name in items:
        if url in done:
            continue
        dest = args.data_dir / "raw" / slug / name
        try:
            size, sha = _download(url, dest)
        except (urllib.error.URLError, OSError) as e:
            print(f"FAILED {url}: {e}", file=sys.stderr)
            continue
        record = {"slug": slug, "url": url, "path": str(dest.relative_to(args.data_dir)), "size": size, "sha256": sha}
        if dest.suffix.lower() == ".zip":
            record["pdfs"] = _extract_pdfs(dest, dest.parent / "pdf")
        manifest["files"].append(record)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"ok {slug} {name} {size}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
