"""MCP server for the locally fetched Bluetooth SIG specifications: the shared server (primarysource.pdfcorpus.server)
with the bluetooth spec. `primarysource mcp --collection bluetooth` serves `mcp`; it makes no network calls."""

from __future__ import annotations

from primarysource.bluetooth.spec import SPEC
from primarysource.pdfcorpus.server import CorpusServer

SERVER = CorpusServer(SPEC)
mcp = SERVER.mcp


def main() -> None:
    """Serve over stdio (`primarysource mcp --collection bluetooth` is the usual way)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
