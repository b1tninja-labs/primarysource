"""Load the usb corpus: the shared loader (primarysource.pdfcorpus.corpus) with the usb spec."""

from __future__ import annotations

from pathlib import Path

from primarysource.usb.spec import SPEC
from primarysource.pdfcorpus import corpus as _shared
from primarysource.pdfcorpus.corpus import SCHEMA_VERSION, CorpusError

ENV_VAR = SPEC.env_var
FETCH_COMMAND = SPEC.fetch_command
__all__ = ["ENV_VAR", "FETCH_COMMAND", "SCHEMA_VERSION", "Corpus", "CorpusError", "default_corpus_dir", "load_corpus"]


class Corpus(_shared.Corpus):
    """A usb corpus: the shared one with this collection's hooks as defaults."""

    def __init__(self, root: Path, documents: tuple[_shared.Document, ...], defaults: dict[str, str] | None = None) -> None:
        super().__init__(
            root,
            documents,
            defaults or {},
            SPEC.alias,
            fetch_command=SPEC.fetch_command,
            index_command=SPEC.index_command,
            prefix=f"{SPEC.name}_",
        )


def default_corpus_dir() -> Path:
    """``$USBLIB_CORPUS`` if set, else ``corpus/`` in the collection's data directory."""
    return SPEC.corpus_dir()


def load_corpus(root: Path | None = None) -> _shared.Corpus:
    """Read and validate the index; raise ``CorpusError`` whose ``action`` is the fetch command."""
    return _shared.load_corpus(SPEC, root)
