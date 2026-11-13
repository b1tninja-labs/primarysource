"""The RFC series as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

# Tool names stay bare (search, read, cite, ...): rfclib's published interface. A prefix is the owner's call
# (PLAN.md §7, "Tool prefix").
COLLECTION = Collection(
    name="rfc",
    title="RFC series (RFC, BCP, STD, FYI) from the RFC Editor",
    prefix="",
    unit=Unit.PARAGRAPH,
    grammar=RefGrammar(r"(?:RFC|BCP|STD|FYI)\d+"),
    server="primarysource.rfc.mcp.server:mcp",
    cli="primarysource.rfc.cli:main",
)
