"""Free joint ISO/IEC publications named by the IEC sync record.

The record lives in the iec home (`free-sync.json`). It is designations and filenames, not the publication
text. ISO import uses it for two decisions: a joint publication with no clause structure is indexed by page,
and a ref that is not imported yet names the file already on disk. `iso_docs` and the citation say when the
imported text is that free edition.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError
from primarysource.home import collection_home
from primarysource.iso.designation import parse

SYNC_RECORD = "free-sync.json"
_PDF_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)
_MAX_MEMBER = 30_000_000
_MAX_NESTED_ZIP = 80_000_000


@dataclass(frozen=True, slots=True)
class FreeJoint:
    """One free ISO or ISO/IEC edition the IEC sync downloaded."""

    reference: str
    doc: str
    pdf_name: str
    names: frozenset[str]


def iec_home() -> Path:
    return collection_home("iec")


def pdf_name(reference: str) -> str:
    """The file name `iec.sync` would give this designation."""
    slug = _PDF_NAME.sub("_", reference).strip("_")
    return f"{slug}.pdf"


def catalogue(root: Path | None = None) -> dict[str, FreeJoint]:
    """Free joint editions keyed by document id (`7501-2@1997`). Missing or unreadable record is empty."""
    home = iec_home() if root is None else root
    path = home / SYNC_RECORD
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    docs = loaded.get("documents") if isinstance(loaded, dict) else None
    if not isinstance(docs, dict):
        return {}
    found: dict[str, FreeJoint] = {}
    for item in docs.values():
        if not isinstance(item, dict):
            continue
        if not str(item.get("head") or "").upper().startswith("ISO"):
            continue
        reference = str(item.get("reference") or "")
        try:
            designation = parse(reference)
        except LibError:
            continue
        names = {pdf_name(reference)}
        for key in ("iso_path", "path"):
            value = str(item.get(key) or "")
            if value:
                names.add(Path(value).name)
        found[designation.doc] = FreeJoint(designation.label, designation.doc, pdf_name(reference), frozenset(names))
    return found


def lookup(token: str, table: dict[str, FreeJoint] | None = None) -> FreeJoint | None:
    """The free joint edition `token` names: a doc id, or a bare number's newest year."""
    known = catalogue() if table is None else table
    if token in known:
        return known[token]
    number = token.split("@", 1)[0]
    editions = [item for doc, item in known.items() if doc.split("@", 1)[0] == number and "+" not in doc]
    if not editions:
        return None
    return max(editions, key=lambda item: item.doc)


def by_name(name: str, table: dict[str, FreeJoint] | None = None) -> FreeJoint | None:
    """The free joint edition a file name belongs to, or None."""
    known = catalogue() if table is None else table
    for item in known.values():
        if name in item.names:
            return item
    return None


def on_disk(item: FreeJoint, iso_home: Path, root: Path | None = None) -> Path | None:
    """Where that edition's file already is: the iso home first, then the iec pdfs directory."""
    for name in sorted(item.names):
        path = iso_home / name
        if path.is_file():
            return path
    iec = iec_home() if root is None else root
    pdfs = iec / "pdfs"
    for name in sorted(item.names):
        for folder in (pdfs, iec):
            path = folder / name
            if path.is_file():
                return path
    return None


def _score(path: Path, doc: str) -> int:
    """How sure `path` is the joint edition `doc`: the file name, else the cover."""
    from primarysource import identify
    from primarysource.iso.designation import from_filename
    from primarysource.iso.identify import designation_of
    from primarysource.iso.identify import identify as iso_identify

    named = from_filename(path.name)
    if named is not None and named.doc == doc:
        return 1
    try:
        probe = identify.probe_pdf(path)
    except LibError:
        return 0
    best = 0
    for candidate in iso_identify(probe):
        try:
            if designation_of(candidate.designation).doc == doc:
                best = max(best, candidate.score)
        except ValueError:
            continue
    return best


def _safe_member(name: str) -> bool:
    parts = Path(name).parts
    return bool(parts) and parts[0] not in ("", "/", "\\") and ".." not in parts


def _pdfs_in_zip(archive: zipfile.ZipFile, dest: Path, depth: int) -> list[Path]:
    """PDF members, and PDFs inside nested zips, written under `dest`. A member that escapes `dest` is skipped."""
    found: list[Path] = []
    for info in archive.infolist():
        if info.is_dir() or not _safe_member(info.filename):
            continue
        lower = info.filename.lower()
        if lower.endswith(".pdf") and info.file_size <= _MAX_MEMBER:
            target = dest / Path(info.filename).name
            if target.resolve().parent != dest.resolve():
                continue
            target.write_bytes(archive.read(info))
            found.append(target)
        elif lower.endswith(".zip") and depth > 0 and info.file_size <= _MAX_NESTED_ZIP:
            with zipfile.ZipFile(io.BytesIO(archive.read(info))) as nested:
                found.extend(_pdfs_in_zip(nested, dest, depth - 1))
    return found


def place_publication(home: Path, archive: Path, item: FreeJoint, root: Path | None = None) -> Path | None:
    """Copy the joint edition's own PDF out of `archive` into `home`, leaving every other member where it is.

    An already-unpacked artifact directory is preferred to reading the zip. Returns the PDF in `home`, or None
    when the archive holds no PDF of this edition."""
    dest = home / item.pdf_name
    if dest.is_file() and dest.stat().st_size > 1000:
        return dest
    iec = iec_home() if root is None else root
    artifacts = iec / "artifacts" / archive.stem
    candidates = [path for path in artifacts.rglob("*.pdf") if path.is_file()] if artifacts.is_dir() else []
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if not candidates:
            temporary = tempfile.TemporaryDirectory(prefix="iso-joint-")
            with zipfile.ZipFile(archive) as zipped:
                candidates = _pdfs_in_zip(zipped, Path(temporary.name), 3)
        ranked = [(score, path) for path in candidates if (score := _score(path, item.doc)) > 0]
        if not ranked:
            return None
        _best, winner = max(ranked, key=lambda pair: (pair[0], -pair[1].stat().st_size))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(winner, dest)
        return dest
    finally:
        if temporary is not None:
            temporary.cleanup()
