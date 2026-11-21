"""Index the PDFs inside an Open Specifications zip. The zip stays where sync put it.

Each member whose name is an `[MS-...]` PDF is read from the zip, cut at its bookmarks (or one section per
page when it has none), and stored as `extracted/<id>.json`. Serving reads that file. A member that escapes
the zip is skipped. The search index is rebuilt once at the end.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256
from primarysource.model import Document, Section, Unit
from primarysource.msos.catalogue import SETS
from primarysource.msos.sync import WIM_DOC, WIM_ID, WIM_NAME, WIM_PAGE, ZIPS, wim_path

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
EXTRACTED = "extracted"
REBUILD_COMMAND = "primarysource msos index"
IMPORT_COMMAND = "primarysource msos import"
_SPEC = re.compile(r"(?i)(?:\[)?(MS-[A-Z0-9]+(?:-[A-Z0-9]+)*)(?:\])?")
_JUNK = re.compile(r"^\s*$|^(?:Microsoft Word|untitled)|\.(?:docx?|pdf)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    designation: str
    sections: int
    segmenter: str
    note: str = ""


def spec_id(name: str) -> str | None:
    """`[MS-PATCH].pdf` and `MS-CAB.pdf` become `ms-patch` and `ms-cab`."""
    match = _SPEC.search(Path(name).name)
    return match.group(1).lower() if match else None


def _safe(name: str) -> bool:
    parts = Path(name).parts
    return bool(parts) and ".." not in parts and not name.startswith(("/", "\\"))


def read_record(home: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((home / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"documents": {}}
    if isinstance(loaded, dict) and isinstance(loaded.get("documents"), dict):
        return loaded
    return {"documents": {}}


def _write_record(home: Path, record: dict[str, Any]) -> None:
    record["collection"] = "msos"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _unchanged(entry: dict[str, Any] | None, archive: Path, info: zipfile.ZipInfo) -> bool:
    if not entry or entry.get("member") != info.filename or entry.get("zip") != archive.name:
        return False
    try:
        stat = archive.stat()
    except OSError:
        return False
    return entry.get("crc") == info.CRC and entry.get("zip_size") == stat.st_size


def _extract(data: bytes) -> tuple[dict[str, Any], str]:
    from primarysource.readers import pdf

    if len(data) > pdf.MAX_BYTES:
        raise LibError(f"the PDF is {len(data)} bytes, over the {pdf.MAX_BYTES} byte bound", "")
    note = ""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        try:
            extraction = pdf.extract(data, temporary, numbered=True)
        except LibError as exc:
            if "no bookmarks" not in exc.message:
                raise
            extraction = pdf.extract_pages(data, temporary)
            note = "indexed by page"
    finally:
        temporary.unlink(missing_ok=True)
    return extraction, note


def import_member(home: Path, archive: Path, info: zipfile.ZipInfo, *, reindex: bool = True) -> ImportResult:
    """Index one PDF member. The caller has already checked the name and the zip path."""
    doc = spec_id(info.filename)
    if doc is None:
        raise LibError(f"{info.filename} is not an [MS-] specification", "")
    from primarysource.readers.pdf import MAX_BYTES

    if info.file_size > MAX_BYTES:
        raise LibError(
            f"{info.filename} is {info.file_size} bytes uncompressed, over the {MAX_BYTES} byte bound",
            "",
        )
    with zipfile.ZipFile(archive) as zipped:
        data = zipped.read(info)
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{info.filename} is not a PDF", "")
    extraction, note = _extract(data)
    title = str(extraction["title"])
    designation = f"[{doc.upper()}]"
    if _JUNK.search(title) or title.strip() == designation:
        title = ""
    extraction.update({"designation": designation, "doc": doc, "sha256": sha256(data), "title": title})
    atomic_write(
        home / EXTRACTED / f"{doc}.json",
        (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    record = read_record(home)
    record["documents"][doc] = {
        "designation": designation,
        "title": title,
        "set": archive.stem,
        "zip": archive.name,
        "member": info.filename,
        "crc": info.CRC,
        "zip_size": archive.stat().st_size,
        "bytes": len(data),
        "sha256": extraction["sha256"],
        "extractor": extraction["extractor"],
        "segmenter": extraction["segmenter"],
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_record(home, record)
    if reindex:
        rebuild_index(home)
    return ImportResult(doc, designation, len(extraction["sections"]), str(extraction["segmenter"]), note)


def import_wim(home: Path, *, reindex: bool = True) -> ImportResult:
    """Index the Windows Imaging File Format paper downloaded by `sync_wim`."""
    from primarysource.readers import rtf

    path = wim_path(home)
    if not path.is_file():
        raise LibError(f"no {WIM_NAME} in {path.parent}", "", f"primarysource msos sync --only {WIM_ID}")
    data = path.read_bytes()
    digest = sha256(data)
    record = read_record(home)
    entry = record["documents"].get(WIM_DOC)
    if isinstance(entry, dict) and entry.get("sha256") == digest and (home / EXTRACTED / f"{WIM_DOC}.json").is_file():
        return ImportResult(WIM_DOC, "WIM", 0, "outline", "unchanged")
    extraction = rtf.extract(data)
    extraction.update(
        {
            "designation": "WIM",
            "doc": WIM_DOC,
            "sha256": digest,
            "title": "Windows Imaging File Format",
            "source": WIM_PAGE,
        }
    )
    atomic_write(
        home / EXTRACTED / f"{WIM_DOC}.json",
        (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    record = read_record(home)
    record["documents"][WIM_DOC] = {
        "designation": "WIM",
        "title": "Windows Imaging File Format",
        "set": WIM_ID,
        "zip": "",
        "member": WIM_NAME,
        "crc": 0,
        "zip_size": 0,
        "bytes": len(data),
        "sha256": digest,
        "extractor": extraction["extractor"],
        "segmenter": extraction["segmenter"],
        "source": WIM_PAGE,
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_record(home, record)
    if reindex:
        rebuild_index(home)
    return ImportResult(WIM_DOC, "WIM", len(extraction["sections"]), str(extraction["segmenter"]))


def import_zips(home: Path, only: Sequence[str] = ()) -> tuple[list[ImportResult], list[tuple[str, str]]]:
    """Index every new or changed specification PDF in the downloaded zips, and the WIM paper."""
    wanted = set(only)
    done: list[ImportResult] = []
    skipped: list[tuple[str, str]] = []
    record = read_record(home)
    have = record["documents"]
    folder = home / ZIPS
    want_zips = not wanted or bool(wanted - {WIM_ID, WIM_DOC})
    want_wim = not wanted or bool(wanted & {WIM_ID, WIM_DOC})
    if want_zips and not folder.is_dir():
        raise LibError(f"no zips in {folder}", "", "primarysource msos sync")
    names = {item.id for item in SETS}
    archives = sorted(folder.glob("*.zip")) if want_zips else []
    for archive in archives:
        if archive.stem not in names:
            continue
        try:
            zipped = zipfile.ZipFile(archive)
        except zipfile.BadZipFile as exc:
            skipped.append((archive.name, f"not a zip: {exc}"))
            continue
        with zipped:
            for info in zipped.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".pdf") or not _safe(info.filename):
                    continue
                doc = spec_id(info.filename)
                if doc is None:
                    continue
                if wanted and doc not in wanted and archive.stem not in wanted:
                    continue
                entry = have.get(doc)
                if _unchanged(entry if isinstance(entry, dict) else None, archive, info):
                    continue
                try:
                    result = import_member(home, archive, info, reindex=False)
                    print(f"imported {result.doc} {result.sections}", file=sys.stderr, flush=True)
                    done.append(result)
                    have[doc] = read_record(home)["documents"][doc]
                except LibError as exc:
                    skipped.append((f"{archive.stem}:{info.filename}", exc.message))
                    print(f"skip {doc}: {exc.message}", file=sys.stderr, flush=True)
                except MemoryError:
                    skipped.append((f"{archive.stem}:{info.filename}", "out of memory reading the member"))
                    print(f"skip {doc}: out of memory", file=sys.stderr, flush=True)
    if want_wim and (wim_path(home).is_file() or wanted & {WIM_ID, WIM_DOC}):
        try:
            result = import_wim(home, reindex=False)
            if result.note != "unchanged":
                print(f"imported {result.doc} {result.sections}", file=sys.stderr, flush=True)
                done.append(result)
        except LibError as exc:
            skipped.append((WIM_DOC, exc.message))
            print(f"skip {WIM_DOC}: {exc.message}", file=sys.stderr, flush=True)
    if done or (have and not (home / INDEX_FILE).is_file()):
        rebuild_index(home)
    return done, skipped


def documents(home: Path) -> Iterator[Document]:
    record = read_record(home)
    for doc, entry in sorted(record["documents"].items()):
        stored = home / EXTRACTED / f"{doc}.json"
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
        title = f"{entry.get('designation', doc)} {entry.get('title') or ''}".strip()
        yield Document(str(doc), title, Unit.SENTENCE, sections)


def rebuild_index(home: Path) -> int:
    return index.rebuild(home / INDEX_FILE, documents(home), rebuild_command=REBUILD_COMMAND)
