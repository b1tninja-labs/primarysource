"""The ieee collections' HTML reader: the core's `primarysource.readers.html`, plus the `POSIX` profile.

The converter itself moved to the core (`cl.reader_html`); this module re-exports it so `posix.py` and anything
else that imported `primarysource.ieee._html` keeps working unchanged. What stays here is ieee's own rule set.
"""

from __future__ import annotations

from primarysource.readers.html import (
    GENERIC,
    MAX_INDENT,
    MAX_OUTPUT_CHARS,
    Document,
    Heading,
    Link,
    Profile,
    convert,
    fence_language,
    is_chrome,
    join_blocks,
    resolve_href,
    to_plain,
)

__all__ = [
    "GENERIC",
    "MAX_INDENT",
    "MAX_OUTPUT_CHARS",
    "POSIX",
    "Document",
    "Heading",
    "Link",
    "Profile",
    "convert",
    "fence_language",
    "is_chrome",
    "join_blocks",
    "resolve_href",
    "to_plain",
]

POSIX = Profile(
    chrome_classes=frozenset({"navheader", "topofpage"}),
    inner_anchor=True,
    small_print_centre=True,
    plain_blockquote=True,
    rules=False,
)
"""The Open Group's POSIX pages: five rules on top of `GENERIC` (see `Profile` for what each one does)."""
