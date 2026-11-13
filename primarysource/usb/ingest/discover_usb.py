"""Build the catalogue of USB-IF document-library entries and the files each one links to.

Walks the paged listing at https://www.usb.org/documents, opens each document page, and records the
PDF and ZIP links it carries. It writes data/usb-catalog.json. It downloads no specifications.
Requests are throttled to one per second with a generic User-Agent.
"""

from __future__ import annotations

from primarysource.usb.paths import PACKAGE_DATA

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

BASE = "https://www.usb.org"
LISTING = BASE + "/documents?page={page}"
SLUG = re.compile(r"/document-library/([a-z0-9-]+)")
FILE = re.compile(r'href="(https?://[^"]+?\.(?:pdf|zip))"|href="(/sites/default/files/[^"]+?\.(?:pdf|zip))"', re.I)
TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
USER_AGENT = "usblib-discover/0.1 (documentation catalogue)"
DELAY = 1.0


def fetch_text(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"  {url}: HTTP {e.code}", file=sys.stderr)
        return None
    finally:
        time.sleep(DELAY)


def listing_slugs(max_pages: int) -> list[str]:
    seen: list[str] = []
    for page in range(max_pages):
        html = fetch_text(LISTING.format(page=page))
        if html is None:
            break
        slugs = [s for s in dict.fromkeys(SLUG.findall(html)) if s not in seen]
        if not slugs:
            break
        seen.extend(slugs)
        print(f"listing page {page}: {len(slugs)} new, {len(seen)} total", file=sys.stderr)
    return seen


def entry_files(slug: str) -> tuple[str, list[str]]:
    html = fetch_text(f"{BASE}/document-library/{slug}") or ""
    title_m = TITLE.search(html)
    title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else slug
    urls: list[str] = []
    for a, b in FILE.findall(html):
        url = a or (BASE + b)
        if url not in urls:
            urls.append(url)
    return title, urls


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=PACKAGE_DATA / "usb-catalog.json")
    parser.add_argument("--max-pages", type=int, default=40)
    args = parser.parse_args(argv)
    slugs = listing_slugs(args.max_pages)
    entries = []
    for slug in slugs:
        title, files = entry_files(slug)
        entries.append({"slug": slug, "title": title, "files": files})
        print(f"{slug}: {len(files)} file(s)", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"schema": 1, "source": LISTING.format(page="N"), "entries": entries}, indent=2), encoding="utf-8")
    with_files = sum(1 for e in entries if e["files"])
    print(f"wrote {args.out}: {len(entries)} entries, {with_files} with files", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
