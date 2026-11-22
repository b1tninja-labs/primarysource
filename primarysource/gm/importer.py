"""Import GM's OBD PDFs from the collection's home into the corpus the shared skeleton serves.

Each PDF is read once: page count and dates with `pypdf`, page text with `pdftotext -layout` when it is on PATH
(else `pypdf`'s layout mode), cut by `primarysource.gm.segment`. The text goes to `corpus/text/<doc_id>.txt`, the
sections to `corpus/index.json`, and the search index (`sections.sqlite`) is rebuilt. The PDF is not copied.
A file whose sha256 matches an earlier one in the same run is a duplicate and is named, not imported twice; an
unchanged file already in the corpus is skipped unless `force`.

`corpus/install.json` records, per document, what the extractor could and could not do: the pages, the characters,
the pages with no text layer (a scan would show here) and the segmenter.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from primarysource.errors import LibError
from primarysource.fsutil import atomic_write
from primarysource.gm.designation import designate
from primarysource.gm.paths import home
from primarysource.gm.segment import segment
from primarysource.pdfcorpus import fts
from primarysource.pdfcorpus.corpus import load_corpus
from primarysource.pdfcorpus.index import document_from_dict, sha256_file, write_index
from primarysource.pdfcorpus.models import Document
from primarysource.pdfcorpus.pages import read_pages
from primarysource.pdfcorpus.spec import CorpusSpec

_COPY_SUFFIX = re.compile(r"\(\d+\)$")
INSTALL_RECORD = "install.json"
NO_TEXT_BELOW = 20  # a page with fewer non-space characters than this has no usable text layer


@dataclass(frozen=True, slots=True)
class Imported:
    """One file's outcome: `status` is `imported`, `unchanged`, `duplicate` or `skipped`, `note` says why."""

    file: str
    status: str
    doc_id: str = ""
    pages: int = 0
    sections: int = 0
    no_text_pages: tuple[int, ...] = ()
    segmenter: str = ""
    note: str = ""


@dataclass
class Report:
    results: list[Imported] = field(default_factory=list)
    indexed_sections: int = 0


def _kind(doc_id: str) -> str:
    if doc_id.startswith("mode6-"):
        return "mode6"
    if "OBDG" in doc_id.upper():
        return "diagnostics"
    return "pages"


def _load_index(root: Path) -> dict[str, Document]:
    try:
        raw = json.loads((root / "index.json").read_text(encoding="utf-8"))
        return {d.doc_id: d for d in (document_from_dict(x) for x in raw["documents"])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _record(root: Path) -> dict[str, Any]:
    try:
        loaded = json.loads((root / INSTALL_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"documents": {}}
    return loaded if isinstance(loaded, dict) and isinstance(loaded.get("documents"), dict) else {"documents": {}}


def import_files(
    spec: CorpusSpec,
    files: Sequence[Path],
    *,
    root: Path | None = None,
    doc_id: str | None = None,
    force: bool = False,
) -> Report:
    """Import `files` into the corpus at `root` (default `spec.corpus_dir()`), then rebuild the search index."""
    root = spec.corpus_dir() if root is None else root
    if doc_id is not None and len(files) != 1:
        raise LibError("--id names one document, so it takes exactly one file", "import the files one at a time")
    documents = _load_index(root)
    record = _record(root)
    report = Report()
    digests: dict[str, str] = {}
    (root / "text").mkdir(parents=True, exist_ok=True)
    for path in files:
        try:
            designation = designate(path.name, doc_id)
            digest = sha256_file(path)
            if digest in digests:
                report.results.append(
                    Imported(
                        path.name,
                        "duplicate",
                        digests[digest],
                        note=f"identical to the copy already imported as {digests[digest]}",
                    )
                )
                continue
            digests[digest] = designation.doc_id
            known = documents.get(designation.doc_id)
            if known is not None and known.sha256 == digest and not force and (root / known.text_file).is_file():
                report.results.append(
                    Imported(path.name, "unchanged", designation.doc_id, sections=len(known.sections))
                )
                continue
            pages, extractor, created = read_pages(path)
            cut = segment(pages, _kind(designation.doc_id))
            text_file = f"text/{designation.doc_id}.txt"
            atomic_write(root / text_file, ("\n".join(cut.lines) + "\n").encode("utf-8"))
            documents[designation.doc_id] = Document(
                doc_id=designation.doc_id,
                number=designation.number,
                title=designation.title,
                date=created or designation.year or "unknown",
                status="final",
                url=f"local copy of {path.name}",
                sha256=digest,
                text_file=text_file,
                sections=tuple(cut.sections),
            )
            blank = tuple(n for n, page in enumerate(pages, start=1) if len("".join(page.split())) < NO_TEXT_BELOW)
            record["documents"][designation.doc_id] = {
                "file": path.name,
                "sha256": digest,
                "pages": len(pages),
                "characters": sum(len(page) for page in pages),
                "no_text_pages": list(blank),
                "extractor": extractor,
                "segmenter": cut.kind,
                "sections": len(cut.sections),
                "imported": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            report.results.append(
                Imported(path.name, "imported", designation.doc_id, len(pages), len(cut.sections), blank, cut.kind)
            )
        except LibError as exc:
            report.results.append(
                Imported(path.name, "skipped", note=f"{exc.message} ({exc.hint})" if exc.hint else exc.message)
            )
    if any(r.status == "imported" for r in report.results):
        ordered = sorted(documents.values(), key=lambda d: d.doc_id.casefold())
        write_index(root / "index.json", ordered)
        atomic_write(root / INSTALL_RECORD, (json.dumps(record, indent=2) + "\n").encode("utf-8"))
        corpus = load_corpus(spec, root)
        report.indexed_sections = fts.build(corpus)
    return report


def pdfs_in(directory: Path) -> list[Path]:
    """The PDFs directly in `directory`, by name."""
    if not directory.is_dir():
        raise LibError(f"{directory} is not a folder", "set PRIMARYSOURCE_GM_HOME to the folder holding GM's PDFs")
    found = sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
        key=lambda p: (bool(_COPY_SUFFIX.search(p.stem)), p.name.casefold()),
    )
    if not found:
        raise LibError(f"no PDFs in {directory}", "put GM's PDFs there, or set PRIMARYSOURCE_GM_HOME")
    return found


def main(argv: Sequence[str]) -> int:
    """`primarysource gm import [FILE ...] [--id DOC_ID] [--force]` (no file: every PDF in the gm home)."""
    import argparse
    import sys

    from primarysource.gm.spec import SPEC

    parser = argparse.ArgumentParser(prog="primarysource gm import", description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", type=Path, help=f"PDFs (default: every PDF in {home()})")
    parser.add_argument("--id", dest="doc_id", help="document id for one file whose name is not recognised")
    parser.add_argument("--force", action="store_true", help="re-import files whose sha256 is unchanged")
    args = parser.parse_args(list(argv))
    try:
        files = list(args.files) or pdfs_in(home())
        report = import_files(SPEC, files, doc_id=args.doc_id, force=args.force)
    except LibError as exc:
        print(exc.as_text(), file=sys.stderr)
        return 2
    for r in report.results:
        if r.status == "imported":
            blank = f", {len(r.no_text_pages)} page(s) without text" if r.no_text_pages else ""
            print(
                f"imported   {r.doc_id}: {r.pages} pages, {r.sections} sections ({r.segmenter}){blank}  <- {r.file}"
            )
        elif r.status == "unchanged":
            print(f"unchanged  {r.doc_id}: {r.sections} sections  <- {r.file}")
        else:
            print(f"{r.status:<10} {r.file}: {r.note}")
    if report.indexed_sections:
        print(f"indexed {report.indexed_sections} section(s) into {SPEC.corpus_dir() / fts.INDEX_FILE}")
    return 1 if any(r.status == "skipped" for r in report.results) else 0
