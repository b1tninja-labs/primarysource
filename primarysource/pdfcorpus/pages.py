"""Page texts of a local PDF for the collections that import PDFs into a `pdfcorpus` (gm, bluetooth).

`pdftotext -layout` when it is on PATH and returns every page, else `pypdf`'s layout mode. `pypdf` is always needed
(page count and dates), so a missing one is the shared reader's `LibError` naming the extra. Nothing is written.
"""

from __future__ import annotations

import io
from pathlib import Path

from primarysource.errors import LibError
from primarysource.readers import pdf as reader

MAX_PAGES = 5000


def read_pages(path: Path) -> tuple[list[str], str, str]:
    """(page texts, extractor label `name version`, creation month `YYYY-MM` or "")."""
    pypdf = reader._pypdf()  # noqa: SLF001 - the shared reader's own "pypdf is missing" error with its install hint
    try:
        pdf = pypdf.PdfReader(io.BytesIO(path.read_bytes()), strict=False)
        count = len(pdf.pages)
        if count > MAX_PAGES:
            raise LibError(f"{path.name} has {count} pages, over the {MAX_PAGES} bound", "")
        created = ""
        meta = pdf.metadata
        when = getattr(meta, "creation_date", None) if meta is not None else None
        if when is not None:
            created = f"{when.year:04d}-{when.month:02d}"
        pages = reader.pdftotext_pages(path, count, layout=True)
        if pages is not None:
            backend = reader.pdftotext_backend() or reader.Backend("pdftotext", "unknown")
        else:
            pages = [str(page.extract_text(extraction_mode="layout") or "") for page in pdf.pages]
            backend = reader.Backend("pypdf", str(pypdf.__version__))
    except LibError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types on a damaged file
        raise LibError(f"could not read {path.name}: {type(exc).__name__}: {exc}", "check the file is a PDF") from exc
    return pages, backend.label(), created
