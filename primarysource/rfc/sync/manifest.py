"""Fetch and parse the official RFC Index manifest (rfc-index.xml).

Source of truth: https://www.rfc-editor.org/rfc-index.xml
Schema:          https://www.rfc-editor.org/rfc-index.xsd

The manifest lists every published document (RFC/BCP/STD/FYI) with title,
authors, dates, statuses, stream, abstract, and the full obsoletes/updates/
is-also relation graph.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..config import MANIFEST_URL, USER_AGENT, network_mode, require_network
from ..fsutil import atomic_write_bytes

NS = "{https://www.rfc-editor.org/rfc-index}"

# entry tag -> series code ('rfc-not-issued-entry' is intentionally skipped)
_SERIES_BY_TAG = {
    "rfc-entry": "RFC",
    "bcp-entry": "BCP",
    "std-entry": "STD",
    "fyi-entry": "FYI",
    "ien-entry": "IEN",
}

_REL_TAGS = {
    "obsoletes": "obsoletes",
    "obsoleted-by": "obsoleted_by",
    "updates": "updates",
    "updated-by": "updated_by",
    "is-also": "alias",
}

_MONTHS = {
    m: i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"], 1)
}


@dataclass
class DocMeta:
    doc_id: str
    series: str
    title: str | None = None
    authors: list[dict] = field(default_factory=list)
    pub_date: str | None = None          # ISO 'YYYY-MM-01' when known
    status: str | None = None            # publication-status at time of publishing
    current_status: str | None = None    # status today (may differ if promoted)
    stream: str | None = None
    wg: str | None = None
    area: str | None = None
    doi: str | None = None
    errata_url: str | None = None
    page_count: int | None = None
    keywords: list[str] = field(default_factory=list)
    abstract: str | None = None
    formats: list[str] = field(default_factory=list)
    draft_name: str | None = None
    relations: list[tuple[str, str]] = field(default_factory=list)  # (kind, target)


def download_manifest(dest: Path, force: bool = False, max_age_hours: float = 24.0) -> Path:
    """Download rfc-index.xml into dest (a file path), reusing a fresh copy."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not force and dest.exists():
        age_h = (time.time() - dest.stat().st_mtime) / 3600.0
        if age_h < max_age_hours:
            return dest
    if dest.exists() and network_mode() == "offline":
        return dest              # stale but usable; offline means offline
    require_network("the RFC index (rfc-index.xml)")
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        r = client.get(MANIFEST_URL, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        atomic_write_bytes(dest, r.content)
    return dest


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _parse_entry(entry: ET.Element, series: str) -> DocMeta | None:
    doc_id = _text(entry.find(f"{NS}doc-id"))
    if not doc_id:
        return None
    meta = DocMeta(doc_id=doc_id.strip().upper(), series=series)
    meta.title = _text(entry.find(f"{NS}title"))

    for a in entry.findall(f"{NS}author"):
        name = _text(a.find(f"{NS}name"))
        if name:
            meta.authors.append({"name": name, "role": _text(a.find(f"{NS}title"))})

    date = entry.find(f"{NS}date")
    if date is not None:
        year = _text(date.find(f"{NS}year"))
        month = _MONTHS.get(_text(date.find(f"{NS}month")) or "", None)
        if year:
            meta.pub_date = f"{year}-{month:02d}-01" if month else f"{year}-01-01"

    meta.status = _text(entry.find(f"{NS}publication-status"))
    meta.current_status = _text(entry.find(f"{NS}current-status"))
    meta.stream = _text(entry.find(f"{NS}stream"))
    wg = _text(entry.find(f"{NS}wg_acronym"))
    meta.wg = None if wg and wg.upper() == "NON WORKING GROUP" else wg
    meta.area = _text(entry.find(f"{NS}area"))
    meta.doi = _text(entry.find(f"{NS}doi"))
    meta.errata_url = _text(entry.find(f"{NS}errata-url"))
    meta.draft_name = _text(entry.find(f"{NS}draft"))
    pc = _text(entry.find(f"{NS}page-count"))
    if pc and pc.isdigit():
        meta.page_count = int(pc)

    fmt = entry.find(f"{NS}format")
    if fmt is not None:
        meta.formats = [t.strip().lower() for t in
                        (x.text or "" for x in fmt.findall(f"{NS}file-format")) if t]

    kw = entry.find(f"{NS}keywords")
    if kw is not None:
        meta.keywords = [t for t in (_text(x) for x in kw.findall(f"{NS}kw")) if t]

    abstract = entry.find(f"{NS}abstract")
    if abstract is not None:
        paras = [_text(p) for p in abstract.findall(f"{NS}p")]
        joined = "\n\n".join(p for p in paras if p)
        meta.abstract = joined or None

    for tag, kind in _REL_TAGS.items():
        rel_el = entry.find(f"{NS}{tag}")
        if rel_el is not None:
            for d in rel_el.findall(f"{NS}doc-id"):
                target = _text(d)
                if target:
                    meta.relations.append((kind, target.strip().upper()))
    return meta


def parse_manifest(path: Path) -> list[DocMeta]:
    root = ET.parse(path).getroot()
    out: list[DocMeta] = []
    for entry in root:
        tag = entry.tag.split("}")[-1]
        series = _SERIES_BY_TAG.get(tag)
        if series is None:
            continue  # e.g. rfc-not-issued-entry
        meta = _parse_entry(entry, series)
        if meta is not None:
            out.append(meta)
    return out
