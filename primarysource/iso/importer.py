"""Import the owner's own purchased ISO PDFs into `$PRIMARYSOURCE_HOME/iso/`.

`import_folder` reads every new or changed PDF in the home; `import_file` takes one file and, optionally, the
designation printed on its cover. Which standard a PDF is comes from its content first (`iso.identify`: the cover's
`Reference number` line and the running header), then its file name, so a renamed download still imports and a
file named for the wrong standard is caught. A PDF another collection knows (an ITU-T Recommendation, a NIST
publication) is refused with that collection's command. Each PDF is read once with `readers.pdf.extract` (cut at
its bookmarks, or at its numbered headings when it has none, as older ISO editions do) into
`extracted/<key>.json`, which is what serving reads, so the PDF is never copied and serving never needs `pypdf`.
`install.json` records the designation, the sha256, size and mtime of the source, the extractor and the
segmenter. When the PDF's title metadata is useless (`Microsoft Word - C038770e.doc`), the English title on the
cover is used. After an import the core FTS5 index (`index.sqlite`) is rebuilt atomically. Nothing here fetches,
and nothing records the buyer's watermark or a distributor's tracking string.
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
from primarysource.iso.identify import cover_title, useful_title
from primarysource.model import Document, Section, Unit

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
EXTRACTED = "extracted"
REBUILD_COMMAND = "primarysource iso index"
IMPORT_COMMAND = "primarysource iso import"


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    designation: str
    sections: int
    headings_found: int
    segmenter: str = ""
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
    record["collection"] = "iso"
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def designate(path: Path, explicit: str | None = None) -> tuple[Designation, str]:
    """Which ISO standard `path` is, and a note when the file name disagrees with the cover. An explicit
    designation wins; then the PDF's own content (a score of 3 or more: the cover, or a running header and the
    file name); then the file name. A PDF another collection recognises is refused with that collection's
    command, and one nobody recognises asks for `--designation`."""
    if explicit:
        return parse(explicit), ""
    from primarysource import identify
    from primarysource.iso.identify import designation_of
    from primarysource.iso.identify import identify as iso_identify

    probe = identify.probe_pdf(path)
    named = from_filename(path.name)
    ours = sorted(iso_identify(probe), key=lambda c: -c.score)
    if ours and ours[0].score >= 3:
        found = designation_of(ours[0].designation)
        note = ""
        if named is not None and named.doc != found.doc:
            note = f"the file name says {named.label}, the PDF says {found.label}; using the PDF"
        return found, note
    if named is not None:
        return named, ""
    others = [c for c in identify.identify(probe, identify.registered_hooks()) if c.collection != "iso"]
    if others:
        best = others[0]
        raise LibError(
            f"{path.name} is {best.designation}, a {best.collection} document, not an ISO standard", "", best.command
        )
    raise LibError(
        f"{path.name}: no ISO designation found on its cover, in its running headers or in its file name",
        "",
        f'{IMPORT_COMMAND} "{path}" --designation "ISO/IEC 9899:2024"  (as printed on the cover)',
    )


def import_file(home: Path, path: Path, designation: str | None = None, *, reindex: bool = True) -> ImportResult:
    """Identify, extract and record one PDF. Nothing is recorded unless the PDF reads and can be cut into
    sections (at its bookmarks, or at three or more numbered headings)."""
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
        raise LibError(f"{path.name} is not a PDF", "", "use the PDF as delivered by the ISO store")
    found, note = designate(path, designation)
    extraction = pdf.extract(data, path, numbered=True)
    digest = sha256(data)
    extraction.update({"designation": found.label, "doc": found.doc, "sha256": digest})
    if not useful_title(str(extraction["title"]), found.label):
        from primarysource import identify

        extraction["title"] = cover_title(identify.probe_pdf(path))
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


def import_folder(home: Path, folder: Path | None = None) -> tuple[list[ImportResult], list[tuple[str, str]]]:
    """Import every PDF directly in `folder` (default: the home itself) that is new or changed since its last
    import, identifying each from its content. Returns what was imported and what was skipped, with the reason.
    The index is rebuilt once at the end when anything was imported."""
    folder = folder or home
    if not folder.is_dir():
        raise LibError(
            f"{folder} does not exist",
            "",
            f"create it (or set PRIMARYSOURCE_ISO_HOME to where your ISO PDFs are), put the PDFs in it, then "
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
