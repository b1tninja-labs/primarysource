"""ITU-T recommendations as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

# itulib's refs: X.690§11.6¶2, with an edition key after the number (X.690#2008-11§8.1). ¶n counts sentences of
# the extracted clause. The tools already carry the itu_ prefix.
COLLECTION = Collection(
    name="itu",
    title="ITU-T recommendations (the ASN.1 family X.680-X.697), fetched by the user",
    prefix="itu_",
    unit=Unit.SENTENCE,
    grammar=RefGrammar(r"[A-Z]\.\d+(?:\.\d+)?(?:#[\d-]+)?"),
    server="primarysource.itu.mcp:build",
    cli="primarysource.itu.cli:main",
)
