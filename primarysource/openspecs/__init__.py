"""Microsoft Open Specifications, as published on Microsoft Learn.

The source is the public table-of-contents tree at learn.microsoft.com/en-us/openspecs/: one `toc.json` for the
library, one per family, and one per specification, whose entries are the section pages. The on-disk hive is
not in that tree; `fetch` also records the archived Technet article `TN-CC750583`, and `sync` chapters it by
heading. `primarysource openspecs fetch` stores that catalog. `primarysource openspecs sync` downloads each
page and builds the search index under `$PRIMARYSOURCE_HOME/openspecs/`. The text is not redistributed with
this package. `docs/openspecs.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.openspecs.site import DOC_ID, SECTION_ID
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection


class _Refs:
    """`library.parse_ref`, imported on first use so the collection loads without walking the catalog."""

    _grammar = RefGrammar(DOC_ID.pattern, SECTION_ID.pattern)

    def parse(self, text: str) -> Ref:
        from primarysource.openspecs.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


OPENSPECS = Collection(
    name="openspecs",
    title="Microsoft Open Specifications",
    prefix="openspecs_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.openspecs.server:server",
    cli="primarysource.openspecs.cli:main",
)
"""Refs: `openspecs:MS-SMB2§2.2.1¶2`. `§` is a Learn page (a section number, or a slug). `¶n` is the nth block of
that page. The prefix is optional and the document id is case-insensitive."""

__all__ = ["OPENSPECS"]
