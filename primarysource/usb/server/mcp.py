"""MCP server for the local USB-IF specifications: the shared server (primarysource.pdfcorpus.server) with the
usb spec. `primarysource mcp --collection usb` serves `mcp`."""

from __future__ import annotations

from primarysource.usb.spec import SPEC
from primarysource.pdfcorpus.server import CorpusServer

SERVER = CorpusServer(SPEC)
mcp = SERVER.mcp


def main() -> None:
    """Serve over stdio (`primarysource mcp --collection usb` is the usual way)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
