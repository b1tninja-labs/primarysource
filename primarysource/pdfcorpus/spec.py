"""What a fetched-document collection tells the shared skeleton about itself."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CorpusSpec:
    """One collection's names and hooks.

    `env_var` overrides the corpus directory (the old `NISTLIB_CORPUS`), else `default_dir()` gives it.
    `read_defaults(root)` returns `{publication name: doc_id}` for bare names with no revision, and `alias(key)`
    turns a normalised reference into such a name (NIST: "nist sp 800-53" -> "800-53"). Both are optional.
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

    def corpus_dir(self) -> Path:
        env = os.environ.get(self.env_var)
        return Path(env) if env else self.default_dir()

    @property
    def fetch_hint(self) -> str:
        return f"Run `{self.fetch_command}` to download the corpus."
