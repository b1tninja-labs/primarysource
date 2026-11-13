"""The shared skeleton of a fetched-document collection: user-fetched PDFs, extracted text, a section index,
a search index in the core FTS5 index (`fts`), five tools (search, read, outline, info, cite) and an MCP server.

nistlib and usblib were one skeleton copied twice (primarysource PLAN.md §1). This is the one copy. A collection
supplies a `CorpusSpec` (its names, where its corpus lives, its fetch command, and optional hooks such as NIST's
default-revision aliases) and gets the loader, the tools and the server from here. Fetching and splitting stay in
the collection for now (ROADMAP `us.base_segmenter`).
"""

from __future__ import annotations

from primarysource.pdfcorpus.corpus import Corpus, CorpusError, load_corpus
from primarysource.pdfcorpus.models import Document, Section
from primarysource.pdfcorpus.spec import CorpusSpec

__all__ = ["Corpus", "CorpusError", "CorpusSpec", "Document", "Section", "load_corpus"]
