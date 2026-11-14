"""IEEE standards: two collections in one subpackage, `posix` by `[posix]` (no
dependency) and `ieee802` by `[ieee]` (`pypdf`).

- `posix`: IEEE Std 1003.1-2024, which is The Open Group Base Specifications Issue 8 (one text, also published
  as ISO/IEC/IEEE 9945). The free HTML edition, downloaded by the user and imported from its archive.
- `ieee802`: IEEE 802 standards a user obtained from the IEEE GET Program, as PDFs.

They are two collections, not one, because licence, placement and pin are per collection and the Open Group's
terms differ from IEEE's GET terms (PLAN.md §5.8). `docs/ieee.md` is the user-facing description.

Importing this package needs nothing outside the standard library: `pypdf` is imported only by the 802 PDF
import, so `posix` works without it, and `mcp` only by `server.py` when a collection is served
(`primarysource mcp --collection posix`). `primarysource posix ...` runs `cli.py`.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

POSIX_DOC = r"posix-[0-9]{4}"
"""An edition of POSIX by year: `posix-2024`."""

POSIX_PAGE = r"[a-z]+(?:/[A-Za-z0-9_\[][A-Za-z0-9_.+\-]*)?"
"""A page of the HTML edition by its path without `.html`: `functions/open`, `utilities/pax`, `basedefs/stdio.h`,
`basedefs/V1_chap03`, `xrat/V4_xcu_chap01`. `utilities/[` is the one page whose name starts with `[`."""

IEEE802_DOC = r"802(?:\.[0-9]+[A-Za-z]*)*-[0-9]{4}"
"""An 802 standard by number and year: `802.1Q-2022`, `802.3-2022`, `802.1AB-2016`, `802.15.4-2020`."""

POSIX = Collection(
    name="posix",
    title="IEEE Std 1003.1-2024 / The Open Group Base Specifications Issue 8",
    prefix="posix_",
    unit=Unit.BLOCK,
    grammar=RefGrammar(POSIX_DOC, POSIX_PAGE),
    server="primarysource.ieee.server:posix_server",
    cli="primarysource.ieee.cli:posix_main",
)
"""Refs: `posix-2024§functions/open#tag_17_372_03¶2`. `§` names the page, `#` an HTML anchor on it. `¶n` counts
converted blocks (a paragraph, a list item, a code block, a table, a definition term): with an anchor, the blocks
under that heading, the heading itself excluded and its subsections included; with only a page, every block of
the page, headings included."""

IEEE802 = Collection(
    name="ieee802",
    title="IEEE 802 standards (IEEE GET Program)",
    prefix="ieee802_",
    unit=Unit.SENTENCE,
    grammar=RefGrammar(IEEE802_DOC),
    server="primarysource.ieee.server:ieee802_server",
    cli="primarysource.ieee.cli:ieee802_main",
    identify="primarysource.ieee.identify:identify",
)
"""Refs: `802.1Q-2022§5.4¶2`. `§` names a numbered clause or annex (`5.4`, `A.1`); `¶n` is the nth sentence of the
clause's extracted text, because a PDF gives sentences, not paragraphs."""

__all__ = ["IEEE802", "POSIX"]
