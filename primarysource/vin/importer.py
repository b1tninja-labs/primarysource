"""Import General Motors VIN filings into `$PRIMARYSOURCE_HOME/vin/`.

`import_folder` reads every new or changed PDF in the home; `import_file` takes one file. Which filing a PDF is
comes from its cover (`vin.identify`: the model-year VIN standard and a 49 CFR Part 565 cite). Each PDF is read
once, one section per page, into `extracted/<id>.json`, which is what serving reads, so the PDF is never copied
and serving never needs `pypdf`. `install.json` records the label, the sha256, size and mtime of the source, the
extractor and the segmenter. After an import the core FTS5 index (`index.sqlite`) is rebuilt from those
extractions. Nothing here fetches.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256
from primarysource.model import Document, Section, Unit
from primarysource.vin.identify import Filing, filing_from_label, from_filename, identify

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
EXTRACTED = "extracted"
REBUILD_COMMAND = "primarysource vin index"
IMPORT_COMMAND = "primarysource vin import"
_TITLE_LIMIT = 160


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    label: str
    sections: int
    segmenter: str = "pages"
    note: str = ""


def read_record(home: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((home / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"documents": {}}
    if isinstance(loaded, dict) and isinstance(loaded.get("documents"), dict):
        return loaded
    return {"documents": {}}


def _write_record(home: Path, record: dict[str, Any]) -> None:
    record["collection"] = "vin"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def document_label(entry: dict[str, Any], doc: str) -> str:
    """The label recorded for one filing (`label`, or `designation` in an older record)."""
    return str(entry.get("label") or entry.get("designation") or doc)


def designate(path: Path) -> tuple[Filing, str]:
    """Which GM filing `path` is, and a note when the file name disagrees with the cover. A PDF another
    collection recognises is refused with that collection's command."""
    from primarysource import identify as identify_mod

    probe = identify_mod.probe_pdf(path)
    ours = identify(probe)
    if ours and ours[0].score >= 3:
        found = filing_from_label(ours[0].designation)
        named = from_filename(path.name)
        note = ""
        if named is not None and named.year != found.year:
            note = f"the file name says {named.label}, the PDF says {found.label}; using the PDF"
        return found, note
    others = [c for c in identify_mod.identify(probe, identify_mod.registered_hooks()) if c.collection != "vin"]
    if others:
        best = others[0]
        raise LibError(
            f"{path.name} is {best.designation}, a {best.collection} document, not a GM VIN filing",
            "",
            best.command,
        )
    raise LibError(
        f"{path.name}: not a General Motors VIN filing under 49 CFR Part 565",
        "the cover states the VIN standard for a model year and cites 49 CFR Part 565",
        f'{IMPORT_COMMAND} "{path}"',
    )


def _pages(data: bytes, path: Path) -> dict[str, Any]:
    """One section per PDF page. `pypdf` is imported here, so serving an already-imported filing does not need it."""
    from primarysource.readers.pdf import MAX_BYTES, MAX_PAGES, _pypdf

    if len(data) > MAX_BYTES:
        raise LibError(f"{path.name} is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    pypdf = _pypdf()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        count = len(reader.pages)
        if count > MAX_PAGES:
            raise LibError(f"{path.name} has {count} pages, over the {MAX_PAGES} bound", "")
        if count < 1:
            raise LibError(f"{path.name} has no pages", "")
        sections: list[dict[str, Any]] = []
        for number, page in enumerate(reader.pages, start=1):
            text = str(page.extract_text() or "").strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = lines[0] if lines else f"page {number}"
            if len(title) > _TITLE_LIMIT:
                title = title[: _TITLE_LIMIT - 3].rstrip() + "..."
            sections.append({"id": str(number), "title": title, "text": text, "depth": 0, "page": number})
    except LibError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on hostile input
        raise LibError(f"could not read {path.name}: {type(exc).__name__}: {exc}", "is it a PDF?") from exc
    return {"extractor": "pypdf", "segmenter": "pages", "pages": count, "sections": sections}


def import_file(home: Path, path: Path, *, reindex: bool = True) -> ImportResult:
    """Identify, extract and record one PDF. Nothing is recorded unless the cover is a GM Part 565 filing and
    the PDF yields at least one page. The PDF itself is not copied."""
    if not path.is_file():
        raise LibError(f"{path} is not a file", "", f"check the path, then {IMPORT_COMMAND}")
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError as exc:
        raise LibError(f"cannot read {path}: {exc}", "", f"check the file, then {IMPORT_COMMAND}") from exc
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{path.name} is not a PDF", "")
    found, note = designate(path)
    extracted = _pages(data, path)
    digest = sha256(data)
    extracted.update({"doc": found.doc, "label": found.label, "title": found.label, "sha256": digest})
    atomic_write(
        home / EXTRACTED / f"{found.key}.json",
        (json.dumps(extracted, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    record = read_record(home)
    previous = record["documents"].get(found.doc)
    entry: dict[str, Any] = {
        "label": found.label,
        "key": found.key,
        "title": found.label,
        "source": str(path),
        "sha256": digest,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "extractor": extracted["extractor"],
        "segmenter": extracted["segmenter"],
        "pages": extracted["pages"],
        "sections": len(extracted["sections"]),
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if isinstance(previous, dict) and previous.get("sha256") == digest and previous.get("source_url"):
        entry["source_url"] = previous["source_url"]
    record["documents"][found.doc] = entry
    _write_record(home, record)
    if reindex:
        rebuild_index(home)
    return ImportResult(found.doc, found.label, len(extracted["sections"]), str(extracted["segmenter"]), note)


def _unchanged(entry: dict[str, Any] | None, path: Path) -> bool:
    if not entry or entry.get("source") != str(path):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return entry.get("size") == stat.st_size and entry.get("mtime_ns") == stat.st_mtime_ns


def import_folder(home: Path, folder: Path | None = None) -> tuple[list[ImportResult], list[tuple[str, str]]]:
    """Import every PDF directly in `folder` (default: the home itself) that is new or changed since its last
    import. Returns what was imported and what was skipped, with the reason. The index is rebuilt once at the
    end when anything was imported."""
    folder = folder or home
    if not folder.is_dir():
        raise LibError(
            f"{folder} does not exist",
            "",
            f"create it (or set PRIMARYSOURCE_VIN_HOME to where the GM VIN filings are), put the PDFs in it, then "
            f"{IMPORT_COMMAND}",
        )
    record = read_record(home)
    by_source = {entry.get("source"): entry for entry in record["documents"].values()}
    done: list[ImportResult] = []
    skipped: list[tuple[str, str]] = []
    for path in sorted(p for p in folder.iterdir() if _is_pdf(p)):
        if _unchanged(by_source.get(str(path)), path):
            skipped.append((path.name, "already imported, unchanged"))
            continue
        try:
            done.append(import_file(home, path, reindex=False))
        except LibError as exc:
            skipped.append((path.name, exc.message + (f"; {exc.action}" if exc.action else "")))
    if done:
        rebuild_index(home)
    return done, skipped


def _lines(text: str) -> tuple[str, ...]:
    return tuple(line for line in text.split("\n") if line.strip())


def documents(home: Path) -> Iterator[Document]:
    """Every imported filing as a core `Document`, one section per page, lines as units."""
    record = read_record(home)
    for doc, entry in sorted(record["documents"].items()):
        stored = home / EXTRACTED / f"{entry['key']}.json"
        try:
            raw = json.loads(stored.read_text(encoding="utf-8"))
            sections = tuple(
                Section(str(item["id"]), str(item["title"]), _lines(str(item["text"])), int(item.get("depth", 0)))
                for item in raw["sections"]
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibError(
                f"the extraction of {document_label(entry, doc)} is unreadable: {exc}",
                "",
                f"re-import it: {IMPORT_COMMAND}",
            ) from exc
        yield Document(doc, document_label(entry, doc), Unit.SENTENCE, sections)


def rebuild_index(home: Path) -> int:
    """Rebuild the search index from every stored extraction; returns the number of sections indexed."""
    return index.rebuild(home / INDEX_FILE, documents(home), rebuild_command=REBUILD_COMMAND)
