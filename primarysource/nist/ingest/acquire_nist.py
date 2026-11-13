"""Download the in-scope PDFs named in data/nist-catalog.json into data/corpus/<doc_id>.pdf.

Each download goes to a .part file and is renamed only when complete. The result must start with ``%PDF``.
data/acquired-nist.json records url, path, size and sha256 per file. A file already present whose sha256
matches the manifest is skipped. Requests are throttled to one per second with a generic User-Agent.
Pass --dry-run to print the plan and the total size (from HEAD requests) before downloading anything.
"""

from __future__ import annotations

from primarysource.nist.paths import PACKAGE_DATA

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

USER_AGENT = "nistlib-acquire/0.1 (documentation corpus)"
DELAY = 1.0
CHUNK = 1 << 20


def _size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except (urllib.error.URLError, TimeoutError):
        return None
    finally:
        time.sleep(DELAY)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp, part.open("wb") as out:
            while chunk := resp.read(CHUNK):
                if size == 0 and not chunk.startswith(b"%PDF"):
                    raise OSError("response does not start with %PDF")
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size == 0:
            raise OSError("empty response")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
        time.sleep(DELAY)
    return size, digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=PACKAGE_DATA / "nist-catalog.json")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    items = [e for e in catalog["entries"] if e["in_scope"]]
    if args.dry_run:
        total = 0
        for e in items:
            size = _size(e["pdf_url"])
            total += size or 0
            print(f"{e['doc_id']:<20} {size or '?':>10}  {e['pdf_url']}")
        print(f"{len(items)} files, {total / 1e9:.2f} GB known", file=sys.stderr)
        return 0
    manifest_path = args.data_dir / "acquired-nist.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {"schema": 1, "files": []}
    )
    by_id = {f["doc_id"]: f for f in manifest["files"]}
    failed = 0
    for e in items:
        doc_id = e["doc_id"]
        dest = args.data_dir / "corpus" / f"{doc_id}.pdf"
        old = by_id.get(doc_id)
        if old and dest.exists() and _sha256_file(dest) == old["sha256"]:
            continue
        try:
            if (
                dest.exists() and not old
            ):  # a file placed earlier (the PIV set): record it, never overwrite
                size, sha = dest.stat().st_size, _sha256_file(dest)
            else:
                size, sha = _download(e["pdf_url"], dest)
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            print(f"FAILED {e['pdf_url']}: {err}", file=sys.stderr)
            failed += 1
            continue
        record = {
            "doc_id": doc_id,
            "url": e["pdf_url"],
            "path": f"corpus/{doc_id}.pdf",
            "size": size,
            "sha256": sha,
        }
        by_id[doc_id] = record
        manifest["files"] = list(by_id.values())
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"ok {doc_id} {size}", file=sys.stderr)
    print(f"{len(items) - failed} ok, {failed} failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
