"""A local-only volume of a publisher's PDFs, behind the terms-acknowledgement gate.

`primarysource/iso` taught the shape: the owner's own PDFs sit in a home folder, `import` reads each once with
`readers.pdf.extract` into a stored extraction plus the core FTS5 index, the PDF is never copied, and serving reads
the stored text, so it needs no `pypdf`. What is ISO's in that package is the designation logic. What is left is
this package, driven by a `LocalPdfSpec` that a collection fills in: its name and title, a function that names a
file (`gm`, `can`), how to cut it (at its bookmarks or numbered headings, or one section per page for tables), and
its `terms.Terms`, whose gate every import and every read passes through. `iso` itself is not rebuilt on it: moving
it would change what its existing users see (`docs/terms-gate.md`).

Why a new package and not `pdfcorpus`: `pdfcorpus` is the skeleton of a *fetched* corpus (a fetch command, a
download directory, NIST-style revisions). A local volume has no fetch, one document per file the owner put there,
and an acknowledgement record, so nothing of `pdfcorpus` would be reused but the FTS5 index, which the core
provides directly.

Modules: `spec` (the spec), `refs` (the ref parser), `store` (import and the record), `library` (read, outline,
search, cite, docs), `cli` (`primarysource <name> ...`), `server` (the MCP tools).
"""

from __future__ import annotations

from primarysource.localpdf.refs import LocalRefs
from primarysource.localpdf.spec import DOC_PATTERN, SECTION_PATTERN, DocId, LocalPdfSpec

__all__ = ["DOC_PATTERN", "SECTION_PATTERN", "DocId", "LocalPdfSpec", "LocalRefs"]
