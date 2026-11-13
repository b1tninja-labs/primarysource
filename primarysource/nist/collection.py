"""NIST publications (SP 800, FIPS) as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

# Tool names are still nistlib's bare ones (search, read, outline, info, cite); the `nist_` prefix is
# ROADMAP ns.tool_prefix. Its tools take (doc, section) or lines, not a ref string yet (ns.base_ref).
COLLECTION = Collection(
    name="nist",
    title="NIST publications (SP 800, SP 1800, FIPS), fetched by the user",
    prefix="",
    unit=Unit.BLOCK,
    grammar=RefGrammar(r"[a-z][a-z0-9.-]*"),
    server="primarysource.nist.server.mcp:mcp",
    cli="primarysource.nist.collection:main",
)


def main(argv: Sequence[str]) -> int:
    """`primarysource nist fetch ...` (download, extract, index) and `primarysource nist oscal ...`."""
    commands = {"fetch": "primarysource.nist.ingest.fetch", "oscal": "primarysource.nist.ingest.oscal"}
    if not argv or argv[0] not in commands:
        print(f"usage: primarysource nist {{{','.join(commands)}}} [args]", flush=True)
        return 2
    import importlib

    module = importlib.import_module(commands[argv[0]])
    return int(module.main(list(argv[1:])))
