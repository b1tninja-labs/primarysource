"""`primarysource gm ...`: the collection's own commands."""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str]) -> int:
    """`primarysource gm import [FILE ...]` reads GM's PDFs into the corpus and indexes them;
    `primarysource gm index` rebuilds the search index from the imported text."""
    if argv and argv[0] == "index":
        from primarysource.gm.spec import SPEC
        from primarysource.pdfcorpus import fts

        return fts.main(SPEC, argv[1:])
    if argv and argv[0] == "import":
        from primarysource.gm import importer

        return importer.main(argv[1:])
    print("usage: primarysource gm {import,index} [args]", flush=True)
    return 2
