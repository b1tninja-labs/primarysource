"""Where the cavp collection keeps imported vector sets: `$PRIMARYSOURCE_HOME/cavp`, else the per-user
`primarysource/cavp` (`primarysource.home.collection_home`). Never the working directory, never the package."""

from __future__ import annotations

from pathlib import Path

from primarysource.cavp.model import Store
from primarysource.home import collection_home


def store_dir() -> Path:
    return collection_home("cavp")


def open_store() -> Store:
    return Store(store_dir())
