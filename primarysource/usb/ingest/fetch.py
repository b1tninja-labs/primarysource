"""``usblib-fetch``: download the publications in data/sources.toml, extract their text and write the index.

This is the only module that touches the network, and only for URLs listed in sources.toml.
"""

from __future__ import annotations

from primarysource.usb.paths import data_dir as default_data_dir, sources_file

import argparse
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from primarysource.usb.ingest.extract import (
    ExtractError,
    extract_text,
    find_pdftotext,
    split_sections,
)
from primarysource.usb.ingest.index import read_index, sha256_bytes, sha256_file, write_index
from primarysource.usb.ingest.sources import Source, SourcesError, load_sources
from primarysource.usb.models import Document

USER_AGENT = "usblib-fetch/0.1 (corpus fetcher; one request per listed URL)"
TIMEOUT_SECONDS = 120
MAX_BYTES = 200 * 1024 * 1024


class FetchError(RuntimeError):
    """Raised when one document cannot be fetched or verified."""


def download(url: str, *, timeout: float = TIMEOUT_SECONDS) -> bytes:
    """GET ``url`` and return the body, which must look like a PDF."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body: bytes = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchError(f"download failed for {url}: {error}") from error
    if len(body) > MAX_BYTES:
        raise FetchError(f"{url}: larger than {MAX_BYTES} bytes, refusing")
    if not body.startswith(b"%PDF-"):
        raise FetchError(f"{url}: response is not a PDF")
    return body


def check_digest(doc_id: str, actual: str, expected: str) -> None:
    """Raise FetchError when a recorded digest exists and differs from ``actual``."""
    if expected and actual != expected:
        raise FetchError(
            f"{doc_id}: sha256 {actual} does not match the recorded {expected}"
        )


def _store(pdf: Path, data: bytes) -> None:
    temp = pdf.with_name(pdf.name + ".part")
    temp.write_bytes(data)
    os.replace(temp, pdf)


def obtain_pdf(
    source: Source, corpus: Path, recorded: str, from_file: Path | None
) -> str:
    """Make ``corpus/<doc_id>.pdf`` exist with a matching digest and return that digest.

    ``recorded`` is the digest from sources.toml, or failing that the one recorded by an earlier run.
    A file already in place whose digest matches (or for which none is recorded) is kept. A mismatching
    file is replaced by a fresh copy, which is itself verified before it is kept.
    """
    pdf = corpus / f"{source.doc_id}.pdf"
    if from_file is not None:
        data = from_file.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise FetchError(f"{source.doc_id}: {from_file} is not a PDF")
        digest = sha256_bytes(data)
        check_digest(source.doc_id, digest, source.sha256)
        if not (pdf.exists() and sha256_file(pdf) == digest):
            _store(pdf, data)
        return digest
    if pdf.exists():
        digest = sha256_file(pdf)
        if not recorded or digest == recorded:
            return digest
    data = download(source.url)
    digest = sha256_bytes(data)
    check_digest(source.doc_id, digest, recorded)
    _store(pdf, data)
    return digest


def build_document(source: Source, corpus: Path, digest: str) -> Document:
    """Extract text for ``source`` into the corpus and return its index entry."""
    text = extract_text(corpus / f"{source.doc_id}.pdf")
    text_name = f"{source.doc_id}.txt"
    (corpus / text_name).write_text(text, encoding="utf-8", newline="")
    return Document(
        doc_id=source.doc_id,
        number=source.number,
        title=source.title,
        date=source.date,
        status=source.status,
        url=source.url,
        sha256=digest,
        text_file=text_name,
        sections=split_sections(text),
    )


def parse_from_files(values: Sequence[str]) -> dict[str, Path]:
    """Parse ``DOC_ID=PATH`` arguments."""
    result: dict[str, Path] = {}
    for value in values:
        doc_id, sep, path = value.partition("=")
        if not sep or not doc_id or not path:
            raise SourcesError(f"--from-file expects DOC_ID=PATH, got {value!r}")
        result[doc_id] = Path(path)
    return result


def run(data_dir: Path, from_files: dict[str, Path], only: Sequence[str]) -> int:
    """Fetch, verify, extract and index. Returns the process exit code."""
    sources = load_sources(sources_file(data_dir))
    known = {s.doc_id for s in sources}
    unknown = sorted((set(from_files) | set(only)) - known)
    if unknown:
        raise SourcesError(f"not in sources.toml: {', '.join(unknown)}")
    find_pdftotext()
    corpus = data_dir / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    index_path = corpus / "index.json"
    previous = {d.doc_id: d for d in read_index(index_path)}
    wanted = set(only) | set(from_files) if (only or from_files) else known
    documents: list[Document] = []
    failures = 0
    for source in sources:
        old = previous.get(source.doc_id)
        if source.doc_id not in wanted:
            if old is not None and (corpus / old.text_file).exists():
                documents.append(old)
            continue
        recorded = source.sha256 or (old.sha256 if old else "")
        try:
            digest = obtain_pdf(source, corpus, recorded, from_files.get(source.doc_id))
            document = build_document(source, corpus, digest)
        except (FetchError, ExtractError, OSError) as error:
            print(f"{source.doc_id}: {error}", file=sys.stderr)
            failures += 1
            continue
        note = "" if source.sha256 else " (digest recorded in index.json)"
        print(
            f"{source.doc_id}: {len(document.sections)} sections, sha256 {digest[:12]}{note}"
        )
        documents.append(document)
    write_index(index_path, documents)
    print(f"wrote {index_path} with {len(documents)} document(s)")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="usblib-fetch", description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="directory holding sources.toml and corpus/ (default: $USBLIB_DATA, else the collection's home)",
    )
    parser.add_argument(
        "--from-file",
        action="append",
        default=[],
        metavar="DOC_ID=PATH",
        help="use a PDF you already have for DOC_ID instead of downloading it (repeatable)",
    )
    parser.add_argument(
        "doc_ids",
        nargs="*",
        help="only these documents (default: all, or those named by --from-file)",
    )
    args = parser.parse_args(argv)
    try:
        return run(args.data_dir, parse_from_files(args.from_file), args.doc_ids)
    except (SourcesError, ExtractError) as error:
        print(f"usblib-fetch: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
