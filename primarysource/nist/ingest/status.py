"""Publication status of each corpus document, read from the bulk data the library already holds.

Three sources, each checked on its own:

* the CSRC listing (``data/nist-catalog.json``, written by ``discover_nist``): the status NIST gives each
  publication (Final, Draft, Withdrawn, ...), and whether it is current;
* the OSCAL catalogue's own revision history (``metadata/revisions``): the versions NIST released and when;
* the front matter of the PDF text: a draft carries "Draft" or "Initial Public Draft" on its first pages.

A document's default status is the one NIST's listing gives its publication. The OSCAL history supplies the
newest release of that publication, so a family can be resolved to its current final revision without a
hand-written table.
"""

from __future__ import annotations

from primarysource.nist.paths import PACKAGE_DATA, corpus_dir

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

OSCAL_NS = "{http://csrc.nist.gov/ns/oscal/1.0}"
_DOC_ID = re.compile(r"^sp(?P<series>\d+)-(?P<number>\d+)(?P<letter>(?:(?!r\d)[a-z])?)(?:r(?P<rev>\d+))?")
_DRAFT = re.compile(r"\b(initial public draft|draft)\b", re.I)
_FRONT_MATTER_CHARS = 4000
# The main document of a publication, not a baseline profile of it ("sp800-53r5-high-oscal").
_MAIN_CATALOGUE = re.compile(r"^sp\d+-\d+[a-z]?(r\d+)?(-oscal)?$")
DEFAULTS_FILE = "defaults.json"
DEFAULTS_SCHEMA = 1


@dataclass(frozen=True)
class Release:
    version: str
    last_modified: str  # YYYY-MM-DD


@dataclass(frozen=True)
class DocumentStatus:
    doc_id: str
    csrc_number: str | None  # e.g. "800-53 Rev. 5", None when the listing has no such publication
    csrc_status: str | None  # "Final", "Draft", "Withdrawn", ... as NIST lists it
    csrc_current: bool  # the listing marks it "final and current"
    latest_release: Release | None  # newest OSCAL release, when the document is an OSCAL catalogue
    pdf_marked_draft: bool | None  # None when there is no PDF text to read
    oscal_status: str | None  # the catalogue's own publication-status prop, lowercased; None when absent
    framework: str | None = None  # the catalogue's framework-identifier prop, lowercased ("csf")
    variant: str | None = None  # a baseline profile's name ("low"), None for the main catalogue


_VARIANT = re.compile(r"^sp\d+-\d+[a-z]?(?:r\d+)?-([a-z]+)-oscal$")


def csrc_number_for(doc_id: str) -> str | None:
    """The CSRC number a corpus id stands for: ``sp800-53r5-oscal`` -> ``800-53 Rev. 5``.

    An id without a revision keeps no "Rev." part: ``sp800-218`` -> ``800-218``, ``sp800-218a`` -> ``800-218A``.
    """
    m = _DOC_ID.match(doc_id)
    if m is None:
        return None
    base = f"{m.group('series')}-{m.group('number')}{(m.group('letter') or '').upper()}"
    rev = m.group("rev")
    return base if rev is None else f"{base} Rev. {rev}"


def publication_key(csrc_number: str) -> str:
    """The publication a CSRC number belongs to, without its revision: ``800-53 Rev. 5`` -> ``800-53``."""
    return csrc_number.split(" Rev.")[0]


def load_csrc(path: Path) -> dict[str, list[dict]]:
    """Rows of ``nist-catalog.json`` grouped by their CSRC number."""
    rows: dict[str, list[dict]] = {}
    for row in json.loads(path.read_text(encoding="utf-8"))["entries"]:
        rows.setdefault(row["number"], []).append(row)
    return rows


def csrc_state(rows: list[dict] | None) -> tuple[str | None, bool]:
    """The status NIST gives a publication, and whether it is current.

    Several rows can share a number (a publication and its earlier drafts); the one marked final is preferred.
    """
    if not rows:
        return None, False
    final = [r for r in rows if r["status"] == "Final"]
    chosen = final[0] if final else rows[0]
    return chosen["status"], chosen["reason"] == "final and current"


def oscal_releases(root: ET.Element) -> list[Release]:
    """Every release the catalogue's revision history lists, oldest first."""
    revisions = root.find(f"{OSCAL_NS}metadata/{OSCAL_NS}revisions")
    if revisions is None:
        return []
    out: list[Release] = []
    for rev in revisions.findall(f"{OSCAL_NS}revision"):
        version = (rev.findtext(f"{OSCAL_NS}version") or "").strip()
        modified = (rev.findtext(f"{OSCAL_NS}last-modified") or "").strip()[:10]
        if version and modified:
            out.append(Release(version, modified))
    return sorted(out, key=lambda r: r.last_modified)


def oscal_prop(root: ET.Element, name: str) -> str | None:
    """The value of the first prop the catalogue states under ``name``, lowercased."""
    for prop in root.iter(f"{OSCAL_NS}prop"):
        if prop.get("name") == name and prop.get("value"):
            return prop.get("value", "").strip().lower()
    return None


def oscal_publication_status(root: ET.Element) -> str | None:
    """The ``publication-status`` prop the catalogue states for itself, lowercased."""
    return oscal_prop(root, "publication-status")


def latest_release(root: ET.Element) -> Release | None:
    releases = oscal_releases(root)
    return releases[-1] if releases else None


def pdf_marked_draft(text: str) -> bool:
    """True when the front matter of a PDF's text says it is a draft."""
    return _DRAFT.search(text[:_FRONT_MATTER_CHARS]) is not None


def document_status(
    doc_id: str,
    csrc_rows: dict[str, list[dict]],
    *,
    oscal_path: Path | None = None,
    pdf_text: str | None = None,
) -> DocumentStatus:
    number = csrc_number_for(doc_id)
    status, current = csrc_state(csrc_rows.get(number) if number else None)
    release = None
    oscal_status = None
    framework = None
    if oscal_path is not None:
        root = ET.parse(oscal_path).getroot()
        release = latest_release(root)
        oscal_status = oscal_publication_status(root)
        framework = oscal_prop(root, "framework-identifier")
    variant = _VARIANT.match(doc_id)
    return DocumentStatus(
        doc_id=doc_id,
        csrc_number=number,
        csrc_status=status,
        csrc_current=current,
        latest_release=release,
        pdf_marked_draft=None if pdf_text is None else pdf_marked_draft(pdf_text),
        oscal_status=oscal_status,
        framework=framework,
        variant=variant.group(1) if variant else None,
    )


def compute_defaults(statuses: Iterable[DocumentStatus]) -> dict[str, str]:
    """Publication -> the doc_id of its default document, for the server to resolve a bare publication number.

    A document with no CSRC number (CSF 2.0, a CSWP) is its own default when its catalogue states it final.
    """
    statuses = list(statuses)
    mapping = {publication_key(s.csrc_number): s.doc_id for s in default_documents(statuses)}
    # A baseline profile is named by its publication and its level: "800-53 low".
    for s in statuses:
        if s.csrc_number and s.csrc_current and s.variant:
            mapping[f"{publication_key(s.csrc_number)} {s.variant}"] = s.doc_id
    # A document with no CSRC number (CSF 2.0, a CSWP) is named by its framework, and is its own default.
    for s in statuses:
        if s.csrc_number is None and s.oscal_status == "final":
            mapping.setdefault((s.framework or s.doc_id).lower(), s.doc_id)
    return dict(sorted(mapping.items()))


def write_defaults(root: Path, mapping: dict[str, str]) -> Path:
    path = root / DEFAULTS_FILE
    path.write_text(
        json.dumps({"schema": DEFAULTS_SCHEMA, "defaults": mapping}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_defaults(root: Path) -> dict[str, str]:
    """The defaults map, or an empty map when none has been written yet."""
    path = root / DEFAULTS_FILE
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != DEFAULTS_SCHEMA:
        return {}
    return dict(raw["defaults"])


def statuses_for_corpus(root: Path, catalog: Path) -> list[DocumentStatus]:
    """Status of every document in ``root/index.json``, from the CSRC listing, OSCAL and the PDF text."""
    rows = load_csrc(catalog)
    raw = json.loads((root / "index.json").read_text(encoding="utf-8"))
    out: list[DocumentStatus] = []
    for doc in raw["documents"]:
        doc_id = doc["doc_id"]
        text = root / doc["text_file"]
        oscal = root / f"{doc_id}.xml"
        out.append(
            document_status(
                doc_id,
                rows,
                oscal_path=oscal if oscal.is_file() else None,
                pdf_text=text.read_text(encoding="utf-8") if text.is_file() else None,
            )
        )
    return out


def main(argv: list[str] | None = None) -> int:
    """Write ``defaults.json`` for a corpus directory: ``python -m primarysource.nist.ingest.status [corpus] [catalog]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else corpus_dir()
    catalog = Path(args[1]) if len(args) > 1 else PACKAGE_DATA / "nist-catalog.json"
    statuses = statuses_for_corpus(root, catalog)
    mapping = compute_defaults(statuses)
    write_defaults(root, mapping)
    for publication, doc_id in mapping.items():
        print(f"{publication}: {doc_id}")
    return 0


def default_documents(statuses: Iterable[DocumentStatus]) -> list[DocumentStatus]:
    """The documents that are the current final revision of their publication.

    A publication qualifies when NIST's listing marks it final and current. Among the corpus documents of one
    publication, the default is the newest by OSCAL release date, or the one without a release when none has one.
    """
    by_number: dict[str, list[DocumentStatus]] = {}
    for s in statuses:
        if s.csrc_number and s.csrc_current and _MAIN_CATALOGUE.match(s.doc_id):
            by_number.setdefault(s.csrc_number, []).append(s)
    defaults: list[DocumentStatus] = []
    for group in by_number.values():
        def newest(s: DocumentStatus) -> str:
            return s.latest_release.last_modified if s.latest_release else ""
        defaults.append(max(group, key=newest))
    return sorted(defaults, key=lambda s: s.doc_id)


if __name__ == "__main__":
    raise SystemExit(main())
