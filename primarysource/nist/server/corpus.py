"""Load the nist corpus: the shared loader (primarysource.pdfcorpus.corpus) with the nist spec."""

from __future__ import annotations

from pathlib import Path

from primarysource.nist.spec import SPEC
from primarysource.pdfcorpus import corpus as _shared
from primarysource.pdfcorpus.corpus import SCHEMA_VERSION, CorpusError

ENV_VAR = SPEC.env_var
FETCH_HINT = SPEC.fetch_hint
__all__ = ["ENV_VAR", "FETCH_HINT", "SCHEMA_VERSION", "Corpus", "CorpusError", "default_corpus_dir", "load_corpus"]


class Corpus(_shared.Corpus):
    """A nist corpus: the shared one with this collection's hooks as defaults."""

    def __init__(self, root: Path, documents: tuple[_shared.Document, ...], defaults: dict[str, str] | None = None) -> None:
        super().__init__(root, documents, defaults or {}, SPEC.alias, SPEC.fetch_hint)


def default_corpus_dir() -> Path:
    """``$NISTLIB_CORPUS`` if set, else ``corpus/`` in the collection's data directory."""
    return SPEC.corpus_dir()


def load_corpus(root: Path | None = None) -> _shared.Corpus:
    """Read and validate the index; raise ``CorpusError`` with a fix-it message."""
    return _shared.load_corpus(SPEC, root)
