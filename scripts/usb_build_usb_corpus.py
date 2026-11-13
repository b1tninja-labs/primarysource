"""Choose one PDF per USB-IF specification entry and build data/sources-usb.toml and data/usb-pdf-choice.json.

Run from the project root: ``python scripts/build_usb_corpus.py``. The index is then built by
``usblib-fetch --data-dir data`` style code in the same run: each chosen PDF is copied from ``data/raw/`` to
``data/corpus/<doc_id>.pdf``, extracted, split, and appended to the existing ``data/corpus/index.json``
(documents already in the index keep their entry and files).

The choice is deliberate, not by text yield: a package holds the clean specification next to redlines, ECNs,
errata and adopter agreements, and the longest PDF is not always the one the entry is named after.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from measure_usb import sequence_errors  # noqa: E402

from primarysource.usb.ingest.extract import extract_text, split_sections  # noqa: E402
from primarysource.usb.ingest.index import read_index, sha256_file, write_index  # noqa: E402
from primarysource.usb.models import Document  # noqa: E402

DATA = ROOT / "data"
CORPUS = DATA / "corpus"
_SKIP = re.compile(
    r"redline|\becn|ecn[-_ .]|_ecn|_ecr|\becr|adopter|agreement|errata|compare|previous|track|changes|"
    r"welcome|reorg|faq|marked",
    re.IGNORECASE,
)
# Entries already in the index under another doc_id; they are not added a second time.
_ALREADY = {"smart-card-ccid-version-11": "usb-ccid-1-1"}

# slug -> (PDF path under data/raw/<slug>/, reason). Everything not listed is chosen by rule: the only PDF,
# or the only PDF left once redlines, ECNs, errata, adopter agreements and comparisons are set aside.
OVERRIDES: dict[str, tuple[str, str]] = {
    "usb-power-delivery": (
        "pdf/USB_PD_R3.3_V1.0_2026_10_16.pdf",
        "entry revision is R3.3 V1.0; the package also holds the R2.0 and R3.2 PDFs",
    ),
    "usb4cv-compliance-test-specification": (
        "pdf/USB4 Logical Layer CTS Rev 2.9 - CLEAN.pdf",
        "UNSURE: package is eight per-part USB4 CTS documents; the Logical Layer CTS is listed first in the entry revision",
    ),
    "usb4r-specification-v20": (
        "pdf/USB4 Specification 2.0 November 2025 - CLEAN.pdf",
        "the USB4 Specification 2.0 proper; the package also holds Re-Timer, DROM, DVSEC, Inter-Domain and Connection Manager documents",
    ),
    "usb4-electrical-compliance-test-specification": (
        "pdf/USB4  Electrical Compliance Test Specification Ver2 1p0 no watermark official release clean.pdf",
        "entry revision is the Router Assembly v2 GEN4 ECTS Rev 1.0; the package also holds the older 1.02 and 1.04 documents",
    ),
    "usb-communications-class-subclass-specifications-network-control-model-devices-v11": (
        "pdf/NCM11_20260205.pdf",
        "NCM 1.1 specification; the other live PDFs are mDNS TCP keepalive notes",
    ),
    "usb3cv-and-xhcicv-compliance-test-specifications": (
        "pdf/USB 3.2 CV Compliance Tests-ver 1.22.pdf",
        "UNSURE: thirteen CTS documents; USB 3.2 CV CTS 1.22 is listed first in the entry revision, xHCI CTS r1.20 is the other half of the title",
    ),
    "usb-20-specification": (
        "pdf/usb_20.pdf",
        "the USB 2.0 base specification (Revision 2.0, April 27, 2000); the rest are supplements, errata and amendments",
    ),
    "class-definitions-communication-devices-12": (
        "pdf/CDC120_with_Errata_and_ECN_through_Apr_3_2025.pdf",
        "UNSURE: CDC 1.2 base class definition with errata merged; alternative is CDC120-20101103-track.pdf (Errata 1, tracked changes)",
    ),
    "usb-authentication-specification-rev-10-ecn-and-errata-through-january-7-2019": (
        "pdf/USB Authentication Mapping Specification 20190118.pdf",
        "UNSURE: first page of this file is the USB Type-C Authentication Specification; alternative is the USB Security Foundation Specification",
    ),
    "battery-charging-v12-spec-and-adopters-agreement": (
        "pdf/BC1.2 plus errata 2012-3-15.pdf",
        "BC 1.2 with errata and ECNs through March 15, 2012 merged in; the other PDFs are the 2010 original and errata-only notes",
    ),
    "mobile-broadband-interface-model-v10-errata-1-and-adopters-agreement": (
        "pdf/MBIM v1 0 - errata-1.pdf",
        "the specification at Errata-1 (May 1, 2013), not the Compare PDF",
    ),
    "errata-updates-cdc-v12-and-wmc-v11-dec-2012": (
        "pdf/2012-08-02-CDC120_errata.pdf",
        "UNSURE: CDC 1.2 as of December 6, 2012 with errata merged; alternative is 2012-07-31-WMC110_errata.pdf (WMC 1.1, July 31, 2012)",
    ),
    "network-control-model-devices-specification-v10-and-errata-and-adopters-agreement": (
        "pdf/NCM10-20101124-track.pdf",
        "NCM 1.0 Errata 1 full text (tracked changes), the only full specification in the package",
    ),
    "usb-audio-devices-release-40-and-adopters-agreement": (
        "pdf/Audio4_with_Errata_and ECN_through_October_09_2026.pdf",
        "Audio 4.0 with errata and ECN merged in; the other PDF is the adopters agreement",
    ),
    "video-class-v15-document-set": (
        "pdf/UVC 1.5 Class specification.pdf",
        "the UVC 1.5 class specification; the rest are payload, transport and example documents",
    ),
    "video-class-v11-document-set": (
        "pdf/USB_Video_Class_1.1.pdf",
        "the UVC 1.1 class specification; the rest are payload, transport and example documents",
    ),
    "audiovideo-device-class-v10-spec-and-adopters-agreement": (
        "pdf/AVFunction v1.0.pdf",
        "UNSURE: AV class function document; alternatives are the AVFormat 1, 2 and 3 documents",
    ),
    "audio-devices-rev-20-and-adopters-agreement": (
        "pdf/Audio20 final.pdf",
        "the Audio 2.0 class definition; Frmts20 and Termt20 are companions",
    ),
    "test-measurement-class-specification": (
        "pdf/USBTMC_1_00.pdf",
        "UNSURE: USBTMC base class; alternative is the USB488 subclass document (also Revision 1.0)",
    ),
}

# Dates the revision text and the first page do not give: read from the revision history or the file name.
DATE_OVERRIDES = {
    "hid-usage-tables-17": "2026-01",  # revision history: 1.7, January 26, 2026
    "embedded-usb2-eusb2-physical-layer-supplement-usb-revision-20-specification-rev-12": "2021-12",  # eUSB2_1p2_20211217.pdf
}

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        ],
        start=1,
    )
}  # fmt: skip
_MONTH_YEAR = re.compile(
    r"\b(?P<m>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?(?P<y>(?:19|20)\d\d)\b"
)
_DAY_MONTH_YEAR = re.compile(
    r"\b\d{1,2}\s+(?P<m>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?P<y>(?:19|20)\d\d)\b"
)
_NUMERIC = re.compile(r"\b(?P<m>\d{1,2})/\d{1,2}/(?P<y>\d{2,4})\b")


def parse_date(text: str) -> str | None:
    """YYYY-MM from the first month-and-year found in ``text``, or None."""
    for pattern in (_DAY_MONTH_YEAR, _MONTH_YEAR):
        m = pattern.search(text)
        if m:
            return f"{m.group('y')}-{_MONTHS[m.group('m').lower()[:3]]:02d}"
    m = _NUMERIC.search(text)
    if m and 1 <= int(m.group("m")) <= 12:
        year = int(m.group("y"))
        year = year if year > 99 else (1900 + year if year > 50 else 2000 + year)
        return f"{year}-{int(m.group('m')):02d}"
    return None


def first_page(pdf: Path) -> str:
    out = subprocess.run(  # noqa: S603
        ["pdftotext", "-f", "1", "-l", "1", "-layout", "-enc", "UTF-8", str(pdf), "-"],  # noqa: S607
        capture_output=True,
        check=False,
    )
    return " ".join(out.stdout.decode("utf-8", "replace").split())


def clean_title(title: str) -> str:
    return " ".join(re.sub("[®™]", "", title).split())


def short_revision(revision: str) -> str:
    head = re.split(r"\s\(|;|,\s|\sper\s", revision)[0].strip()
    return head.replace("Revision", "Rev")


def make_number(title: str, revision: str) -> str:
    base = f"USB-IF {clean_title(title)}"
    rev = short_revision(revision)
    tokens = re.findall(r"\d+(?:\.\d+)+|\d+", rev)
    if rev and tokens and not any(t in base for t in tokens[:1]):
        base = f"{base} {rev}"
    return base


def choose(slug: str, base: Path) -> tuple[str, str]:
    pdfs = sorted(
        str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*.pdf")
    )
    if slug in OVERRIDES:
        rel, reason = OVERRIDES[slug]
        if rel not in pdfs:
            raise SystemExit(f"{slug}: override {rel!r} is not on disk")
        return rel, reason
    if len(pdfs) == 1:
        return pdfs[0], "only PDF for the entry"
    live = [p for p in pdfs if not _SKIP.search(p.rsplit("/", 1)[-1])]
    if len(live) == 1:
        return live[0], (
            "only PDF left after setting aside redlines, ECNs, errata, "
            "adopter agreements and comparisons"
        )
    raise SystemExit(f"{slug}: {len(live)} candidates, add an override: {live}")


def source_url(slug: str, rel: str, acquired: list[dict]) -> tuple[str, str]:
    """(url, note): the file's own URL, or its zip's URL with the member name."""
    name = rel.rsplit("/", 1)[-1]
    mine = [f for f in acquired if f["slug"] == slug]
    if not rel.startswith("pdf/"):
        for f in mine:
            if f["path"].replace("\\", "/").rsplit("/", 1)[-1] == name:
                return f["url"], ""
    holders = [f for f in mine if name in f.get("pdfs", [])]
    if not holders:
        holders = [f for f in mine if f.get("pdfs")]
    if len(holders) != 1:
        raise SystemExit(f"{slug}: cannot tell which download holds {rel!r}")
    return holders[0]["url"], f"member {name!r} of the zip"


def _toml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    classification = json.loads((DATA / "usb-classification.json").read_text("utf-8"))
    acquired = json.loads((DATA / "acquired.json").read_text("utf-8"))["files"]
    entries = [
        e
        for e in classification["entries"]
        if e["class"] == "specification"
        and e.get("status") in ("current", "older-revision")
    ]
    skipped = [
        e
        for e in classification["entries"]
        if e["class"] == "specification"
        and e.get("status") not in ("current", "older-revision")
    ]
    choice: list[dict] = []
    blocks: list[str] = []
    numbers: dict[str, str] = {}
    for e in entries:
        slug = e["slug"]
        if slug in _ALREADY:
            skipped.append({**e, "status": f"already indexed as {_ALREADY[slug]}"})
            continue
        base = DATA / "raw" / slug
        rel, reason = choose(slug, base)
        pdf = base / rel
        page = first_page(pdf)
        date = (
            DATE_OVERRIDES.get(slug)
            or parse_date(e["revision"] or "")
            or parse_date(page[:600])
        )
        if date is None:
            raise SystemExit(f"{slug}: no date in {e['revision']!r} or first page")
        number = make_number(e["title"], e["revision"] or "")
        if number in numbers:
            number = f"{number} [{slug}]"
        numbers[number] = slug
        url, note = source_url(slug, rel, acquired)
        status = "final" if e["status"] == "current" else "superseded"
        choice.append(
            {
                "doc_id": slug,
                "file": f"data/raw/{slug}/{rel}",
                "reason": reason,
                "revision": e["revision"],
                "first_page": page[:200],
                "confident": not reason.startswith("UNSURE"),
            }
        )
        block = [f"# {note}" for _ in [0] if note]
        block += [
            "[[source]]",
            f"doc_id = {_toml(slug)}",
            f"number = {_toml(number)}",
            f"title = {_toml(clean_title(e['title']))}",
            f'date = "{date}"',
            f'status = "{status}"',
            f"url = {_toml(url)}",
        ]
        blocks.append("\n".join(block))
    header = (
        "# USB-IF specifications indexed by usblib, chosen by scripts/build_usb_corpus.py from\n"
        "# data/usb-classification.json (class specification, status current or older-revision).\n"
        "# A comment above an entry says the URL is a zip and names the PDF inside it. The choice of PDF and\n"
        "# the reason for it are in data/usb-pdf-choice.json. sha256 is recorded in corpus/index.json.\n\n"
    )
    (DATA / "sources-usb.toml").write_text(
        header + "\n\n".join(blocks) + "\n", encoding="utf-8", newline="\n"
    )
    (DATA / "usb-pdf-choice.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "choices": choice,
                "skipped": [
                    {"slug": e["slug"], "status": e["status"]} for e in skipped
                ],
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(choice)} chosen, {len(skipped)} skipped")
    return build(choice)


def build(choice: list[dict]) -> int:
    from primarysource.usb.ingest.sources import load_sources

    sources = {s.doc_id: s for s in load_sources(DATA / "sources-usb.toml")}
    CORPUS.mkdir(parents=True, exist_ok=True)
    index_path = CORPUS / "index.json"
    existing = read_index(index_path)
    keep = [d for d in existing if d.doc_id not in sources]
    documents: list[Document] = list(keep)
    report: list[dict] = []
    for c in choice:
        source = sources[c["doc_id"]]
        src_pdf = ROOT / c["file"]
        dst_pdf = CORPUS / f"{source.doc_id}.pdf"
        shutil.copyfile(src_pdf, dst_pdf)
        text = extract_text(dst_pdf)
        text_name = f"{source.doc_id}.txt"
        (CORPUS / text_name).write_text(text, encoding="utf-8", newline="")
        sections = split_sections(text)
        documents.append(
            Document(
                doc_id=source.doc_id,
                number=source.number,
                title=source.title,
                date=source.date,
                status=source.status,
                url=source.url,
                sha256=sha256_file(dst_pdf),
                text_file=text_name,
                sections=sections,
            )
        )
        report.append(
            {
                "doc_id": source.doc_id,
                "pages": text.count("\f"),
                "sections": len(sections),
                "sequence_errors": sequence_errors([s.id for s in sections]),
            }
        )
    write_index(index_path, documents)
    (
        Path(sys.argv[0]).resolve().parent.parent / "data" / "usb-corpus-build.json"
    ).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {index_path}: {len(documents)} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
