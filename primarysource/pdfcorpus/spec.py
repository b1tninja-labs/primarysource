"""What a fetched-document collection tells the shared skeleton about itself."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from primarysource.pdfcorpus.models import Document


@dataclass(frozen=True)
class CorpusSpec:
    """One collection's names and hooks.

    `env_var` overrides the corpus directory (the old `NISTLIB_CORPUS`), else `default_dir()` gives it.
    `read_defaults(root)` returns `{publication name: doc_id}` for bare names with no revision, and `alias(key)`
    turns a normalised reference into such a name (NIST: "nist sp 800-53" -> "800-53"). `standing(document,
    defaults)` is the warning line when this document is not the current text of its publication. All three are
    optional.

    `fetch_command` and `index_command` are what a human runs when the corpus or its search index is missing or
    stale; they become an error's `action:` line. With no `index_command` the fetch command is named, since a fetch
    also builds the index.
    """

    name: str
    server_name: str
    env_var: str
    fetch_command: str
    default_dir: Callable[[], Path]
    instructions: str
    cite_example: str
    read_defaults: Callable[[Path], Mapping[str, str]] | None = None
    alias: Callable[[str], str] | None = None
    standing: Callable[[Document, Mapping[str, str]], str] | None = None
    index_command: str = ""

    def corpus_dir(self) -> Path:
        env = os.environ.get(self.env_var)
        return Path(env) if env else self.default_dir()
