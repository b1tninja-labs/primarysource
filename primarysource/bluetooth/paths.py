"""Where the bluetooth collection keeps its files.

The home is `$PRIMARYSOURCE_BLUETOOTH_HOME`, else `$PRIMARYSOURCE_HOME/bluetooth`, else the per-user
`primarysource/bluetooth`. In it: `catalogue.json` (the SIG's list), `pins.json` (sha256 of each PDF as fetched),
`pdf/<doc_id>.pdf` and `corpus/` (`index.json`, `text/`, `sections.sqlite`). `PRIMARYSOURCE_BLUETOOTH_CORPUS` moves
just the corpus. Nothing is created until a command writes.
"""

from __future__ import annotations

from pathlib import Path

from primarysource.home import collection_home


def home() -> Path:
    return collection_home("bluetooth")


def corpus_dir() -> Path:
    return home() / "corpus"
