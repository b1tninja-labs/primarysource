"""Import the owner's own purchased ISO PDFs into `$PRIMARYSOURCE_HOME/iso/`.

`import_folder` reads every PDF in `purchased/` whose file name carries a designation (as the ISO store names them:
`ISO_IEC_9899_2024(en).pdf`); `import_file` takes one file and, optionally, the designation printed on its cover.
Each PDF is read once with `readers.pdf.extract` into `extracted/<key>.json`, which is what serving reads, so the
PDF is never copied and serving never needs `pypdf`. `install.json` records the designation, the sha256, size and
mtime of the source, and the extractor. After an import the core FTS5 index (`index.sqlite`) is rebuilt atomically.
Nothing here fetches, and nothing records the buyer's watermark.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256
from primarysource.iso.designation import Designation, from_filename, parse
from primarysource.model import Document, Section, Unit

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
PURCHASED = "purchased"
EXTRACTED = "extracted"
REBUILD_COMMAND = "primarysource iso index"
IMPORT_COMMAND = "primarysource iso import"


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    designation: str
    sections: int
    headings_found: int


def read_record(home: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((home / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"documents": {}}
    if isinstance(loaded, dict) and isinstance(loaded.get("documents"), dict):
        return loaded
    return {"documents": {}}


def _write_record(home: Path, record: dict[str, Any]) -> None:
    record["collection"] = "iso"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def import_file(home: Path, path: Path, designation: str | None = None, *, reindex: bool = True) -> ImportResult:
    """Extract one PDF and record it. Nothing is recorded unless the PDF reads and has bookmarks."""
    from primarysource.readers import pdf

    found: Designation | None = parse(designation) if designation else from_filename(path.name)
    if found is None:
        raise LibError(
            f"{path.name}: no ISO designation in the file name",
            "",
            f'{IMPORT_COMMAND} "{path}" --designation "ISO/IEC 9899:2024"  (as printed on the cover)',
        )
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError as exc:
        raise LibError(f"cannot read {path}: {exc}", "", f"check the file, then {IMPORT_COMMAND}") from exc
    if len(data) > pdf.MAX_BYTES:
        raise LibError(f"{path.name} is {len(data)} bytes, over the {pdf.MAX_BYTES} byte bound", "")
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{path.name} is not a PDF", "", "use the PDF as delivered by the ISO store")
    extraction = pdf.extract(data, path)
    digest = sha256(data)
    extraction.update({"designation": found.label, "doc": found.doc, "sha256": digest})
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
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_record(home, record)
    if reindex:
        rebuild_index(home)
    return ImportResult(found.doc, found.label, len(extraction["sections"]), int(extraction["headings_found"]))


def _unchanged(entry: dict[str, Any] | None, path: Path) -> bool:
    if not entry or entry.get("source") != str(path):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return entry.get("size") == stat.st_size and entry.get("mtime_ns") == stat.st_mtime_ns


def import_folder(home: Path, folder: Path | None = None) -> tuple[list[ImportResult], list[tuple[str, str]]]:
    """Import every PDF in `folder` (default `<home>/purchased`) whose file name carries a designation and which is
    new or changed since its last import. Returns what was imported and what was skipped, with the reason. The
    index is rebuilt once at the end when anything was imported."""
    folder = folder or home / PURCHASED
    if not folder.is_dir():
        raise LibError(f"{folder} does not exist", "", f"create it, put your ISO PDFs in it, then {IMPORT_COMMAND}")
    record = read_record(home)
    by_source = {entry.get("source"): entry for entry in record["documents"].values()}
    done: list[ImportResult] = []
    skipped: list[tuple[str, str]] = []
    for path in sorted(p for p in folder.iterdir() if _is_pdf(p)):
        if _unchanged(by_source.get(str(path)), path):
            skipped.append((path.name, "already imported, unchanged"))
            continue
        if from_filename(path.name) is None:
            skipped.append((path.name, "no designation in the file name; import it with --designation"))
            continue
        try:
            done.append(import_file(home, path, reindex=False))
        except LibError as exc:
            skipped.append((path.name, exc.message))
    if done:
        rebuild_index(home)
    return done, skipped


def documents(home: Path) -> Iterator[Document]:
    """Every imported standard as a core `Document`, one section per bookmarked clause, sentences as units."""
    record = read_record(home)
    for doc, entry in sorted(record["documents"].items()):
        stored = home / EXTRACTED / f"{entry['key']}.json"
        try:
            raw = json.loads(stored.read_text(encoding="utf-8"))
            sections = tuple(
                Section(
                    str(s["id"]),
                    str(s["title"]),
                    tuple(line for line in str(s["text"]).split("\n") if line),
                    int(s["depth"]) + 1,
                )
                for s in raw["sections"]
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LibError(
                f"the extraction of {entry.get('designation', doc)} is unreadable: {exc}",
                "",
                f"re-import it: {IMPORT_COMMAND}",
            ) from exc
        title = f"{entry['designation']} {entry.get('title') or ''}".strip()
        yield Document(doc, title, Unit.SENTENCE, sections)


def rebuild_index(home: Path) -> int:
    """Rebuild the search index from every stored extraction; returns the number of sections indexed."""
    return index.rebuild(home / INDEX_FILE, documents(home), rebuild_command=REBUILD_COMMAND)
