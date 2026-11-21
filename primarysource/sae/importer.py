"""Import the owner's own SAE PDFs into `$PRIMARYSOURCE_HOME/sae/`.

The PDF is not copied. The import stores the extraction and a source record (path, sha256, size, mtime)
and rebuilds the search index. Reading the PDF needs `pypdf` (the `[iso]` extra) only at import time.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256
from primarysource.model import Document, Section, Unit
from primarysource.sae.designation import Designation, from_filename, parse

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
EXTRACTED = "extracted"
IMPORT_COMMAND = "primarysource sae import"
REBUILD_COMMAND = "primarysource sae index"


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    designation: str
    sections: int
    headings_found: int
    segmenter: str


def read_record(home: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((home / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"documents": {}}
    if isinstance(loaded, dict) and isinstance(loaded.get("documents"), dict):
        return loaded
    return {"documents": {}}


def _write_record(home: Path, record: dict[str, Any]) -> None:
    record["collection"] = "sae"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def designate(path: Path, explicit: str | None = None) -> Designation:
    if explicit:
        return parse(explicit)
    found = from_filename(path.name)
    if found is None:
        raise LibError(
            f"{path.name}: no SAE designation in the file name",
            "",
            f'{IMPORT_COMMAND} "{path}" --designation "SAE J2534:2002"',
        )
    return found


def tesseract_exe() -> Path | None:
    """Tesseract on PATH, or the per-user Windows install."""
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe"
    return local if local.is_file() else None


def ocr_pages(path: Path) -> list[str]:
    """One string per page. A page with a text layer is kept; a scanned page is read with Tesseract."""
    exe = tesseract_exe()
    if exe is None:
        raise LibError(
            "this PDF has no text layer and Tesseract is not installed",
            "",
            "install Tesseract OCR, then re-import",
        )
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        text = str(page.extract_text() or "")
        if len(text.split()) > 20:
            pages.append(text)
            continue
        images = list(getattr(page, "images", []))
        if not images:
            pages.append(text)
            continue
        blob = max(images, key=lambda item: len(item.data))
        suffix = Path(str(getattr(blob, "name", "page.png"))).suffix or ".png"
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / f"page{number}{suffix}"
            image.write_bytes(blob.data)
            completed = subprocess.run(  # noqa: S603 - exe is tesseract, args are the image path
                [str(exe), str(image), "stdout", "--psm", "3"],
                check=False,
                capture_output=True,
            )
        if completed.returncode != 0:
            raise LibError(f"Tesseract failed on page {number}", "", "re-import after checking the image")
        pages.append(completed.stdout.decode("utf-8", errors="replace"))
    return pages


def _from_pages(data: bytes, texts: list[str]) -> dict[str, Any]:
    from primarysource.readers.bookmarks import split_sentences
    from primarysource.readers.pdf import _pypdf

    pypdf = _pypdf()
    reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
    meta = reader.metadata
    title = str(meta.title) if meta is not None and meta.title else ""
    sections = []
    for number, text in enumerate(texts, start=1):
        sentences = split_sentences(text)
        if not sentences:
            continue
        sections.append(
            {"id": str(number), "title": f"page {number}", "depth": 0, "page": number, "text": "\n".join(sentences)}
        )
    if len(sections) < 1:
        raise LibError("the scan produced no text", "", "check Tesseract, then re-import")
    return {
        "title": title,
        "pages": len(reader.pages),
        "extractor": "tesseract",
        "pypdf": pypdf.__version__,
        "headings_found": 0,
        "segmenter": "tesseract",
        "sections": sections,
    }


def import_file(
    home: Path,
    path: Path,
    designation: str | None = None,
    *,
    reindex: bool = True,
    ocr: Callable[[Path], list[str]] | None = None,
) -> ImportResult:
    """Extract and record one PDF. The PDF itself stays where the caller keeps it.

    A scan with no bookmarks is read with Tesseract, one section per page. `ocr` replaces that step in tests.
    """
    from primarysource.readers import pdf

    if not path.is_file():
        raise LibError(f"{path} is not a file", "", IMPORT_COMMAND)
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError as exc:
        raise LibError(f"cannot read {path}: {exc}", "", IMPORT_COMMAND) from exc
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{path.name} is not a PDF", "", "import the PDF as delivered")
    found = designate(path, designation)
    try:
        extraction = pdf.extract(data, path, numbered=True)
    except LibError as exc:
        if "bookmarks" not in exc.message and "numbered headings" not in exc.message:
            raise
        extraction = _from_pages(data, (ocr or ocr_pages)(path))
    digest = sha256(data)
    extraction.update({"designation": found.label, "doc": found.doc, "sha256": digest})
    home.mkdir(parents=True, exist_ok=True)
    atomic_write(
        home / EXTRACTED / f"{found.key}.json",
        (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    record = read_record(home)
    record["documents"][found.doc] = {
        "designation": found.label,
        "key": found.key,
        "title": extraction["title"],
        "source": str(path),
        "sha256": digest,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "extractor": extraction["extractor"],
        "segmenter": extraction["segmenter"],
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_record(home, record)
    if reindex:
        rebuild_index(home)
    return ImportResult(
        found.doc,
        found.label,
        len(extraction["sections"]),
        int(extraction["headings_found"]),
        str(extraction["segmenter"]),
    )


def documents(home: Path) -> Iterator[Document]:
    record = read_record(home)
    for doc, entry in sorted(record["documents"].items()):
        stored = home / EXTRACTED / f"{entry['key']}.json"
        try:
            raw = json.loads(stored.read_text(encoding="utf-8"))
            sections = tuple(
                Section(
                    str(item["id"]),
                    str(item["title"]),
                    tuple(line for line in str(item["text"]).split("\n") if line),
                    int(item["depth"]) + 1,
                )
                for item in raw["sections"]
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibError(
                f"the extraction of {entry.get('designation', doc)} is unreadable: {exc}",
                "",
                f"re-import it: {IMPORT_COMMAND}",
            ) from exc
        label = str(entry.get("designation") or entry.get("label") or doc)
        title = f"{label} {entry.get('title') or ''}".strip()
        yield Document(doc, title, Unit.SENTENCE, sections)


def rebuild_index(home: Path) -> int:
    return index.rebuild(home / INDEX_FILE, documents(home), rebuild_command=REBUILD_COMMAND)
