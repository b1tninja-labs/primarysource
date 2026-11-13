"""The c2sp collection's Markdown reader: a re-export of the core's `primarysource.readers.markdown`.

The reader moved to the core (`cl.reader_markdown`); this module keeps `primarysource.c2sp.markdown` importable so
the importer, the library and their tests are unchanged.
"""

from __future__ import annotations

from primarysource.readers.markdown import (
    MAX_BYTES,
    MAX_LINE,
    MAX_SECTIONS,
    Heading,
    MarkdownDocument,
    decode,
    parse,
    plain,
    slugify,
)

__all__ = [
    "MAX_BYTES",
    "MAX_LINE",
    "MAX_SECTIONS",
    "Heading",
    "MarkdownDocument",
    "decode",
    "parse",
    "plain",
    "slugify",
]
