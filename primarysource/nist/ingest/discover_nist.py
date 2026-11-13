"""Build data/nist-catalog.json: every FIPS and SP 800 / SP 1800 publication CSRC lists, marked in or out.

CSRC has no machine-readable feed, but its publications search is server-rendered and takes
``ipp-lg=all``, so one request per series returns the whole listing (FIPS: 70 rows, SP: 841 rows).
Candidates (listing status Final, FIPS or SP 800 or SP 1800) then get one detail-page request each,
for the PDF link and any supersession notice. Requests are throttled to one per second with a generic
User-Agent. Nothing is downloaded except HTML pages; PDFs are fetched by ``acquire_nist``.
"""

from __future__ import annotations

from primarysource.nist.paths import PACKAGE_DATA

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

BASE = "https://csrc.nist.gov"
LISTING = (
    BASE + "/publications/search?sortBy-lg=Number%20ASC&viewMode-lg=brief&ipp-lg=all"
    "&series-lg={series}&status-lg=Final&status-lg=Draft&status-lg=Withdrawn"
)
USER_AGENT = "nistlib-discover/0.1 (documentation catalogue)"
DELAY = 1.0
ROW = re.compile(r'<tr id="result-\d+">(.*?)</tr>', re.S)


def fetch_text(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  {url}: {e}", file=sys.stderr)
        return None
    finally:
        time.sleep(DELAY)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_listing(page: str) -> list[dict]:
    rows = []
    for row in ROW.findall(page):

        def g(pattern: str, row: str = row) -> str:
            m = re.search(pattern, row, re.S)
            return _clean(m.group(1)) if m else ""

        rows.append(
            {
                "series": g(r'id="pub-series-\d+">(.*?)</td>'),
                "number": g(r'id="pub-number-\d+">(.*?)</td>'),
                "title": g(r'id="pub-title-link-\d+">(.*?)</a>'),
                "status": g(r'id="pub-status-\d+">(.*?)</td>'),
                "date": g(r'id="pub-release-date-\d+">(.*?)</td>'),
                "href": g(r'href="(/pubs/[^"]+)"'),
            }
        )
    return rows


def parse_detail(page: str) -> dict:
    text = _clean(
        re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    )
    pdf = re.search(r'href="([^"]+)"[^>]*id="pub-local-download-link"', page)
    head = re.search(
        r"Date Published:(.*?)(?:Planning Note|Author\(s\)|Abstract)", text
    )
    sup = re.search(
        r"Superseded By:\s*(.*?)(?:Supersedes:|Planning Note|Author\(s\))", text
    )
    return {
        "pdf_url": pdf.group(1) if pdf else "",
        "date_published": _clean(head.group(1)) if head else "",
        "superseded_by": _clean(sup.group(1)) if sup else "",
    }


def parse_href(href: str) -> dict | None:
    """Split /pubs/<series>/<number>/... into the parts a doc_id and a revision order are built from."""
    parts = href.removeprefix("/pubs/").removesuffix("/final").split("/")
    if parts[0] == "fips":
        num, _, rev = parts[1].partition("-")
        return {
            "base": f"fips{num}",
            "rev": int(rev) if rev.isdigit() else 0,
            "doc_id": f"fips{parts[1]}",
        }
    if parts[0] != "sp" or parts[1] not in {"800", "1800"}:
        return None
    if parts[1] == "1800":
        return {"base": f"sp1800-{parts[2]}", "rev": 0, "doc_id": f"sp1800-{parts[2]}"}
    base = f"sp800-{parts[2]}"
    rev_tok = ""
    rev = 0
    sup = False
    for tok in parts[3:]:
        if re.fullmatch(r"[a-z]", tok) or re.fullmatch(r"(pt|v)\d+", tok):
            base += tok
        elif m := re.fullmatch(r"(r|ver)(\d+)", tok):
            rev, rev_tok = int(m.group(2)), tok
        elif tok.isdigit():
            rev, rev_tok = int(tok), f"-{tok}"
        elif tok == "sup":
            sup = True
        elif re.fullmatch(r"upd\d+", tok):
            pass
        else:
            return None
    if sup:
        base += "-add"
    return {"base": base, "rev": rev, "doc_id": base + rev_tok}


def classify(entries: list[dict]) -> None:
    """Set entry['in_scope'] and entry['reason'] for every entry, in place."""
    best: dict[str, int] = {}
    for e in entries:
        p = e["parts"]
        if e["candidate"] and p and not e["superseded_by"]:
            best[p["base"]] = max(best.get(p["base"], 0), p["rev"])
    for e in entries:
        p = e["parts"]
        if e["series"] not in {"FIPS", "SP 800", "SP 1800"}:
            e["in_scope"], e["reason"] = False, f"outside scope: {e['series']} series"
        elif e["status"] != "Final":
            e["in_scope"], e["reason"] = False, f"status {e['status']}"
        elif e["superseded_by"]:
            e["in_scope"], e["reason"] = False, f"superseded by {e['superseded_by']}"
        elif p and p["rev"] < best.get(p["base"], 0):
            e["in_scope"], e["reason"] = (
                False,
                "older revision; a later final revision is listed",
            )
        elif not e["pdf_url"]:
            e["in_scope"], e["reason"] = False, "no PDF link on CSRC page"
        else:
            e["in_scope"], e["reason"] = True, "final and current"


def series_group(row: dict) -> str:
    if row["series"] == "FIPS":
        return "FIPS"
    return (
        f"SP {row['number'].split('-')[0]}" if row["series"] == "SP" else row["series"]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=PACKAGE_DATA / "nist-catalog.json")
    args = parser.parse_args(argv)
    rows: list[dict] = []
    for series in ("FIPS", "SP"):
        page = fetch_text(LISTING.format(series=series))
        if page is None:
            print(f"cannot list {series}", file=sys.stderr)
            return 1
        found = parse_listing(page)
        print(f"{series}: {len(found)} rows", file=sys.stderr)
        rows += found
    entries = []
    for row in rows:
        group = series_group(row)
        parts = parse_href(row["href"])
        candidate = (
            row["status"] == "Final"
            and group in {"FIPS", "SP 800", "SP 1800"}
            and parts is not None
        )
        entry = {
            "series": group,
            "number": row["number"],
            "title": row["title"],
            "date": row["date"],
            "status": row["status"],
            "detail_url": BASE + row["href"],
            "pdf_url": "",
            "superseded_by": "",
            "doc_id": parts["doc_id"] if parts else "",
            "candidate": candidate,
            "parts": parts,
        }
        if candidate:
            page = fetch_text(entry["detail_url"])
            if page is None:
                print(f"detail failed: {entry['detail_url']}", file=sys.stderr)
            else:
                d = parse_detail(page)
                entry.update(pdf_url=d["pdf_url"], superseded_by=d["superseded_by"])
                if d["date_published"]:
                    entry["date_published"] = d["date_published"]
        entries.append(entry)
    classify(entries)
    for e in entries:
        e.pop("candidate")
        e.pop("parts")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": 1, "source": LISTING.format(series="FIPS|SP"), "entries": entries}
    args.out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    kept = sum(1 for e in entries if e["in_scope"])
    print(f"wrote {args.out}: {len(entries)} entries, {kept} in scope", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
