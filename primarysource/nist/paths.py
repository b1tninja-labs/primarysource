"""Where the nist collection keeps its files (primarysource PLAN.md §5.8).

The data directory holds `sources.toml` overrides and the fetched `corpus/`: `$NISTLIB_DATA` if set (the old
setting), else `primarysource.home.collection_home("nist")`, which is `$PRIMARYSOURCE_HOME/nist` or the per-user
`primarysource/nist`. Never the working directory and never beside the installed package. The tracked metadata
(`sources.toml`, catalogues, digests) ships in the package under `data/`.
"""

from __future__ import annotations

import os
from pathlib import Path

from primarysource.home import collection_home

PACKAGE_DATA = Path(__file__).resolve().parent / "data"


def data_dir() -> Path:
    env = os.environ.get("NISTLIB_DATA")
    return Path(env) if env else collection_home("nist", legacy_app="nistlib")


def corpus_dir() -> Path:
    """`$NISTLIB_CORPUS` if set, else `corpus/` in the data directory."""
    env = os.environ.get("NISTLIB_CORPUS")
    return Path(env) if env else data_dir() / "corpus"


def sources_file(data: Path, name: str = "sources.toml") -> Path:
    """The data directory's own `sources.toml` if it has one, else the one shipped in the package."""
    local = data / name
    return local if local.is_file() else PACKAGE_DATA / name
