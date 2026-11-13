"""USB-IF specifications as a primarysource collection. Importing this needs nothing beyond the core."""

from __future__ import annotations

from collections.abc import Sequence

from primarysource.model import Unit
from primarysource.refs import RefGrammar
from primarysource.registry import Collection

# Tool names are still usblib's bare ones (search, read, outline, info, cite); the `usb_` prefix is
# ROADMAP us.tool_prefix. Its tools take (doc, section) or lines, not a ref string yet (us.base_ref_and_pager).
COLLECTION = Collection(
    name="usb",
    title="USB-IF specifications (CCID and others), fetched by the user",
    prefix="",
    unit=Unit.BLOCK,
    grammar=RefGrammar(r"[a-z][a-z0-9.-]*"),
    server="primarysource.usb.server.mcp:mcp",
    cli="primarysource.usb.collection:main",
)


def main(argv: Sequence[str]) -> int:
    """`primarysource usb fetch ...`: download, extract and index the specifications in sources.toml."""
    if not argv or argv[0] != "fetch":
        print("usage: primarysource usb fetch [args]", flush=True)
        return 2
    from primarysource.usb.ingest import fetch

    return int(fetch.main(list(argv[1:])))
