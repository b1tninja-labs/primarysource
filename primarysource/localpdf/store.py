"""Import a local-PDF collection's files into its home: the extraction, the record and the index.

`import_folder` reads every new or changed PDF in a folder (the home itself by default); `import_file` takes one.
Each PDF is read once with `readers.pdf.extract` into `extracted/<key>.json`, which is what serving reads, so the PDF
is never copied. `install.json` records, per document, the source's path, sha256, size and mtime, the extractor and
the segmenter, and (`terms.RECORD_KEY`) the owner's terms acknowledgement. After an import the core FTS5 index
(`index.sqlite`) is rebuilt atomically. Nothing here fetches.

Every entry point passes the gate first (`terms.require_accepted`): with the owner's variable unset nothing is read,
nothing is written and the home folder is not even created.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource import index, terms
from primarysource.errors import LibError
from primarysource.fsutil import atomic_write, sha256
from primarysource.localpdf.spec import DocId, LocalPdfSpec
from primarysource.model import Document, Section

INSTALL_RECORD = "install.json"
INDEX_FILE = "index.sqlite"
EXTRACTED = "extracted"
_COPY_MARKER = re.compile(r"\s*\(\d+\)$")
_KEY = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*")


@dataclass(frozen=True, slots=True)
class ImportResult:
    doc: str
    label: str
    sections: int
    pages: int
    segmenter: str
    empty_pages: int = 0


def read_record(home: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((home / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"documents": {}}
    if isinstance(loaded, dict) and isinstance(loaded.get("documents"), dict):
        return loaded
    return {"documents": {}}


def _write_record(spec: LocalPdfSpec, home: Path, record: dict[str, Any]) -> None:
    record["collection"] = spec.name
    atomic_write(home / INSTALL_RECORD, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def _is_pdf(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".pdf"


def _order(path: Path) -> tuple[bool, str]:
    """Files with a copy marker (`name (1).pdf`) sort after the file they copy, so a duplicate loses."""
    return bool(_COPY_MARKER.search(path.stem)), path.name.casefold()


def _import_data(
    spec: LocalPdfSpec,
    home: Path,
    path: Path,
    data: bytes,
    found: DocId,
    digest: str,
    environ: Mapping[str, str] | None,
    reindex: bool,
) -> ImportResult:
    from primarysource.readers import pdf

    if not _KEY.fullmatch(found.key):
        raise LibError(f"{path.name}: {spec.name} gave the file the unusable key {found.key!r}", "")
    extraction = pdf.extract(
        data,
        path,
        numbered=spec.pages_per_section is None,
        pages_per_section=spec.pages_per_section,
        page_title=spec.page_title,
        front_matter=spec.front_matter,
    )
    if not any(str(section["text"]).strip() for section in extraction["sections"]):
        raise LibError(
            f"{path.name}: no text could be read from any page (the backend was {extraction['extractor']})",
            "put poppler's `pdftotext` on PATH (table pages are read with it); a scanned PDF has no text to read",
            spec.import_command,
        )
    if spec.clean_text is not None:
        for section in extraction["sections"]:
            section["title"] = spec.clean_text(str(section["title"]))
            section["text"] = spec.clean_text(str(section["text"]))
    title = found.title or str(extraction["title"])
    extraction.update({"title": title, "label": found.label, "doc": found.doc, "sha256": digest})
    atomic_write(
        home / EXTRACTED / f"{found.key}.json", (json.dumps(extraction, ensure_ascii=False) + "\n").encode("utf-8")
    )
    stat = path.stat()
    record = read_record(home)
    record["documents"][found.doc] = {
        "label": found.label,
        "key": found.key,
        "title": title,
        "source": str(path),
        "sha256": digest,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "extractor": extraction["extractor"],
        "segmenter": extraction["segmenter"],
        "pages": extraction["pages"],
        "sections": len(extraction["sections"]),
        "imported": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    terms.record_acceptance(spec.terms, record, [found.doc], environ)
    _write_record(spec, home, record)
    if reindex:
        rebuild_index(spec, home, environ)
    return ImportResult(
        found.doc,
        found.label,
        len(extraction["sections"]),
        int(extraction["pages"]),
        str(extraction["segmenter"]),
        int(extraction.get("empty_pages", 0)),
    )


def _read(path: Path) -> tuple[bytes, str]:
    from primarysource.readers import pdf

    if not path.is_file():
        raise LibError(f"{path} is not a file", "check the path")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise LibError(f"cannot read {path}: {exc}", "check the file") from exc
    if len(data) > pdf.MAX_BYTES:
        raise LibError(f"{path.name} is {len(data)} bytes, over the {pdf.MAX_BYTES} byte bound", "")
    if not data.startswith(b"%PDF-"):
        raise LibError(f"{path.name} is not a PDF", "use the PDF as the publisher delivered it")
    return data, sha256(data)


def _name(spec: LocalPdfSpec, path: Path, digest: str) -> DocId:
    found = spec.name_file(path.name, digest)
    if found is None:
        raise LibError(f"{path.name} is not a file name the {spec.name} collection knows", "")
    return found


def import_file(
    spec: LocalPdfSpec,
    home: Path,
    path: Path,
    *,
    reindex: bool = True,
    environ: Mapping[str, str] | None = None,
) -> ImportResult:
    """Name, extract and record one PDF. Nothing is recorded unless it reads and can be cut into sections."""
    terms.require_accepted(spec.terms, home, f"the import of {path.name}", environ)
    data, digest = _read(path)
    return _import_data(spec, home, path, data, _name(spec, path, digest), digest, environ, reindex)


def _unchanged(entry: dict[str, Any] | None, path: Path) -> bool:
    if not entry or entry.get("source") != str(path):
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return entry.get("size") == stat.st_size and entry.get("mtime_ns") == stat.st_mtime_ns


def import_folder(
    spec: LocalPdfSpec,
    home: Path,
    folder: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[ImportResult], list[tuple[str, str]]]:
    """Import every PDF directly in `folder` (default: the home) that is new or changed since its last import.
    Returns what was imported and what was skipped, with the reason. A file whose bytes are another present
    file's is skipped as `skipped duplicate of <collection>:<doc>` (the one without a copy marker in its name is
    kept); a file the collection cannot name, or a second file with the same document id and other bytes, is
    skipped with that reason. The index is rebuilt once at the end when anything was imported."""
    terms.require_accepted(spec.terms, home, f"the {spec.name} import", environ)
    folder = folder or home
    if not folder.is_dir():
        raise LibError(
            f"{folder} does not exist",
            f"create it (or set {spec.home_variable} to where your {spec.title} PDFs are), put the PDFs in it, "
            f"then {spec.import_command}",
        )
    record = read_record(home)
    by_source = {entry.get("source"): entry for entry in record["documents"].values()}
    by_digest = {str(e.get("sha256")): doc for doc, e in record["documents"].items()}
    sources = {doc: str(e.get("source")) for doc, e in record["documents"].items()}
    digests = {doc: str(e.get("sha256")) for doc, e in record["documents"].items()}
    this_run: set[str] = set()
    done: list[ImportResult] = []
    skipped: list[tuple[str, str]] = []

    def elsewhere(doc: str, path: Path) -> bool:
        """The document is held by a different file that is still there (or was imported in this run)."""
        held = sources.get(doc)
        return held is not None and held != str(path) and (doc in this_run or Path(held).is_file())

    for path in sorted((p for p in folder.iterdir() if _is_pdf(p)), key=_order):
        if _unchanged(by_source.get(str(path)), path):
            skipped.append((path.name, "already imported, unchanged"))
            continue
        try:
            data, digest = _read(path)
            found = _name(spec, path, digest)
            twin = by_digest.get(digest)
            if twin is not None and elsewhere(twin, path):
                skipped.append((path.name, f"skipped duplicate of {spec.name}:{twin}"))
                continue
            if elsewhere(found.doc, path) and digests.get(found.doc) != digest:
                skipped.append(
                    (path.name, f"{spec.name}:{found.doc} is already taken by another file with other bytes")
                )
                continue
            done.append(_import_data(spec, home, path, data, found, digest, environ, False))
        except LibError as exc:
            skipped.append((path.name, exc.message + (f"; {exc.hint}" if exc.hint else "")))
            continue
        this_run.add(found.doc)
        sources[found.doc] = str(path)
        digests[found.doc] = digest
        by_digest[digest] = found.doc
    if done:
        rebuild_index(spec, home, environ)
    return done, skipped


def documents(spec: LocalPdfSpec, home: Path) -> Iterator[Document]:
    """Every imported document as a core `Document`, one section per extracted section."""
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
                f"the extraction of {entry.get('label', doc)} is unreadable: {exc}",
                "",
                f"re-import it: {spec.import_command}",
            ) from exc
        title = f"{entry['label']} {entry.get('title') or ''}".strip()
        yield Document(doc, title, spec.unit, sections)


def rebuild_index(spec: LocalPdfSpec, home: Path, environ: Mapping[str, str] | None = None) -> int:
    """Rebuild the search index from every stored extraction; returns the number of sections indexed. Passes the
    gate: no index is built for a document with no recorded acknowledgement."""
    record = read_record(home)
    terms.require_served(
        spec.terms, record, record["documents"], home, f"the {spec.name} index", spec.import_command, environ
    )
    return index.rebuild(home / INDEX_FILE, documents(spec, home), rebuild_command=spec.rebuild_command)
