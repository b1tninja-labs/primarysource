"""NIST publications (SP 800, FIPS) as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.model import Unit
from primarysource.pdfcorpus.tools import GRAMMAR
from primarysource.registry import Collection

# The server registers the bare names (search, read, outline, info, cite); `primarysource mcp` serves them as
# nist_search, ... and `--bare-names` keeps nistlib's names. Refs: `<doc_id>§<section>` and `<doc_id>:<first>-<last>`.
COLLECTION = Collection(
    name="nist",
    title="NIST publications (SP 800, SP 1800, FIPS), fetched by the user",
    prefix="nist_",
    unit=Unit.BLOCK,
    grammar=GRAMMAR,
    server="primarysource.nist.server.mcp:mcp",
    cli="primarysource.nist.collection:main",
)


def main(argv: Sequence[str]) -> int:
    """`primarysource nist fetch ...` (download, extract, index), `primarysource nist oscal ...`,
    `primarysource nist index` (rebuild the search index from the fetched corpus) and `primarysource nist status`
    (write `defaults.json`, so a bare name such as "NIST SP 800-53" resolves to its current final revision)."""
    commands = {
        "fetch": "primarysource.nist.ingest.fetch",
        "oscal": "primarysource.nist.ingest.oscal",
        "status": "primarysource.nist.ingest.status",
    }
    if argv and argv[0] == "index":
        from primarysource.nist.spec import SPEC
        from primarysource.pdfcorpus import fts

        return fts.main(SPEC, argv[1:])
    if not argv or argv[0] not in commands:
        names = ",".join([*commands, "index"])
        print(f"usage: primarysource nist {{{names}}} [args]", flush=True)
        return 2
    import importlib

    module = importlib.import_module(commands[argv[0]])
    return int(module.main(list(argv[1:])))
