"""Import IEC publications that are not ISO editions into `$PRIMARYSOURCE_HOME/iec/`.

`import_folder` reads every new or changed PDF in the home and in `pdfs/`. A file whose name starts with `ISO`,
or whose designation is already an imported ISO edition, is left to `primarysource iso import`. Each PDF is
read once, at its bookmarks, into `extracted/<key>.json`, which is what serving reads. `install.json` records
the designation, the sha256, size and mtime of the source, the extractor and the segmenter. After an import
the core FTS5 index (`index.sqlite`) is rebuilt. Nothing here fetches.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256
from primarysource.home import collection_home
from primarysource.iec.designation import Designation, from_filename, parse
from primarysource.iec.identify import designation_of
from primarysource.iec.identify import identify as iec_identify
from primarysource.model import Document, Section, Unit

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
EXTRACTED = "extracted"
PDFS = "pdfs"
REBUILD_COMMAND = "primarysource iec index"
IMPORT_COMMAND = "primarysource iec import"
_JUNK_TITLE = re.compile(r"^\s*$|^(?:Microsoft Word|untitled)|\.(?:docx?|pdf)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    designation: str
    sections: int
    headings_found: int
    segmenter: str
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
    record["collection"] = "iec"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def indexed_as_iso(doc: str) -> str | None:
    """The iso document id when `doc` is an edition the iso collection already imported, else None.

    Commented and ACEE documents are never ISO editions. A numbered IEC publication that the iso index holds
    under the same number is the joint edition, already searchable there.
    """
    number = doc.split("@", 1)[0]
    if not number[:1].isdigit():
        return None
    try:
        loaded = json.loads((collection_home("iso") / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    documents = loaded.get("documents") if isinstance(loaded, dict) else None
    if not isinstance(documents, dict):
        return None
    if doc in documents:
        return doc
    hits = [str(key) for key in documents if str(key).split("@", 1)[0] == number]
    return hits[0] if len(hits) == 1 else None


def designate(path: Path, explicit: str | None = None) -> tuple[Designation, str]:
    """Which IEC publication `path` is, and a note when the file name disagrees with the cover."""
    if explicit:
        return parse(explicit), ""
    from primarysource import identify

    probe = identify.probe_pdf(path)
    ours = sorted(iec_identify(probe), key=lambda item: -item.score)
    if not ours:
        raise LibError(
            f"{path.name}: no IEC designation found on its cover, in its running headers or in its file name",
            "",
            f'{IMPORT_COMMAND} "{path}" --designation "IEC 60835-2-1:1990"  (as printed on the cover)',
        )
    found = designation_of(ours[0].designation)
    named = from_filename(path.name)
    note = ""
    if named is not None and (named.number, named.year, named.series) == (found.number, found.year, found.series):
        if named.csv and not found.csv:
            found = named
    elif named is not None and named.doc != found.doc:
        note = f"the file name says {named.label}, the PDF says {found.label}; using the PDF"
    return found, note


def import_file(home: Path, path: Path, designation: str | None = None, *, reindex: bool = True) -> ImportResult:
    """Identify, extract and record one PDF. Nothing is recorded unless the PDF has bookmarks."""
    from primarysource.readers import pdf

    if not path.is_file():
        raise LibError(f"{path} is not a file", "", f"check the path, then {IMPORT_COMMAND}")
    try:
        data = path.read_bytes()
        stat = path.stat()
    except OSError as exc:
        raise LibError(f"cannot read {path}: {exc}", "", f"check the file, then {IMPORT_COMMAND}") from exc
    if len(data) > pdf.MAX_BYTES:
        raise LibError(f"{path.name} is {len(data)} bytes, over the {pdf.MAX_BYTES} byte bound", "")
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{path.name} is not a PDF", "", "use the PDF as delivered by the IEC store")
    found, note = designate(path, designation)
    other = indexed_as_iso(found.doc)
    if other is not None:
        raise LibError(
            f"{found.label} is already indexed as iso:{other}",
            "iec import is for an IEC publication that is not an ISO edition",
            f"primarysource iso read {other}",
        )
    extraction = pdf.extract(data, path, numbered=True)
    digest = sha256(data)
    title = str(extraction["title"])
    if _JUNK_TITLE.search(title) or title.strip() == found.label:
        title = ""
    extraction.update({"designation": found.label, "doc": found.doc, "sha256": digest, "title": title})
    atomic_write(
        home / EXTRACTED / f"{found.key}.json",
        (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    record = read_record(home)
    record["documents"][found.doc] = {
        "designation": found.label,
        "key": found.key,
        "title": title,
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
        note,
    )


def _unchanged(entry: dict[str, Any] | None, path: Path) -> bool:
    if not entry or entry.get("source") != str(path):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return entry.get("size") == stat.st_size and entry.get("mtime_ns") == stat.st_mtime_ns


def _pdfs(home: Path) -> list[Path]:
    found: list[Path] = []
    for folder in (home, home / PDFS):
        if folder.is_dir():
            found.extend(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".pdf")
    return sorted(set(found))


def import_folder(home: Path) -> tuple[list[ImportResult], list[tuple[str, str]]]:
    """Import every IEC PDF in the home and in `pdfs/` that is new or changed. The index is rebuilt once."""
    if not home.is_dir():
        raise LibError(
            f"{home} does not exist",
            "",
            f"create it (or set PRIMARYSOURCE_IEC_HOME), put the PDFs in it, then {IMPORT_COMMAND}",
        )
    record = read_record(home)
    by_source = {entry.get("source"): entry for entry in record["documents"].values()}
    done: list[ImportResult] = []
    skipped: list[tuple[str, str]] = []
    for path in _pdfs(home):
        if path.name.upper().startswith("ISO"):
            skipped.append((path.name, "ISO publication; primarysource iso import"))
            continue
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


def documents(home: Path) -> Iterator[Document]:
    """Every imported publication as a core `Document`, one section per bookmarked clause."""
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
        title = f"{entry['designation']} {entry.get('title') or ''}".strip()
        yield Document(str(doc), title, Unit.SENTENCE, sections)


def rebuild_index(home: Path) -> int:
    """Rebuild the search index from every stored extraction; returns the number of sections indexed."""
    return index.rebuild(home / INDEX_FILE, documents(home), rebuild_command=REBUILD_COMMAND)
