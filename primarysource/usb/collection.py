"""USB-IF specifications as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.model import Unit
from primarysource.pdfcorpus.tools import GRAMMAR
from primarysource.registry import Collection

# The server registers the bare names (search, read, outline, info, cite); `primarysource mcp` serves them as
# usb_search, ... and `--bare-names` keeps usblib's names. Refs: `<doc_id>§<section>` and `<doc_id>:<first>-<last>`.
COLLECTION = Collection(
    name="usb",
    title="USB-IF specifications (CCID and others), fetched by the user",
    prefix="usb_",
    unit=Unit.BLOCK,
    grammar=GRAMMAR,
    server="primarysource.usb.server.mcp:mcp",
    cli="primarysource.usb.collection:main",
)


def main(argv: Sequence[str]) -> int:
    """`primarysource usb fetch ...` (download, extract and index the specifications in sources.toml) and
    `primarysource usb index` (rebuild the search index from the fetched corpus)."""
    if argv and argv[0] == "index":
        from primarysource.pdfcorpus import fts
        from primarysource.usb.spec import SPEC

        return fts.main(SPEC, argv[1:])
    if not argv or argv[0] != "fetch":
        print("usage: primarysource usb {fetch,index} [args]", flush=True)
        return 2
    from primarysource.usb.ingest import fetch

    return int(fetch.main(list(argv[1:])))
