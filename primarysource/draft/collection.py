"""IETF Internet-Drafts as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from primarysource.draft.names import GRAMMAR
from primarysource.model import Unit
from primarysource.registry import Collection

COLLECTION = Collection(
    name="draft",
    title="IETF Internet-Drafts (from the datatracker and the IETF archive)",
    prefix="draft_",
    unit=Unit.PARAGRAPH,
    grammar=GRAMMAR,
    server="primarysource.draft.server:server",
    cli="primarysource.draft.cli:main",
)
"""Refs: `draft-ietf-sidrops-8210bis-17§5.1¶2`. The `-17` is the revision; without it a ref resolves to the latest
stored revision and the result says so. `§` names a section as the draft prints its number (`5.1`, `A.2` for
Appendix A.2) or, for an unnumbered section, a title slug (`abstract`, `security-considerations`). `¶n` counts the
paragraph blocks of that section (paragraphs, lists, figures, tables), as the rfc collection does."""
