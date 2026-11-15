"""Where the gm collection keeps its files.

The home is `$PRIMARYSOURCE_GM_HOME`, else `$PRIMARYSOURCE_HOME/gm`, else the per-user `primarysource/gm`
(`primarysource.home.collection_home`). The owner's GM PDFs go directly in it, as GM published them, and the
import writes its own `corpus/` beside them: `index.json`, `text/<doc_id>.txt`, `sections.sqlite`, `install.json`.
`$PRIMARYSOURCE_GM_CORPUS` moves just the corpus. Nothing is created until an import.
"""

from __future__ import annotations

from pathlib import Path

from primarysource.home import collection_home


def home() -> Path:
    return collection_home("gm")


def corpus_dir() -> Path:
    return home() / "corpus"
