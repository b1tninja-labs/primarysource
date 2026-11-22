"""MCP server for the owner's local GM OBD documents: the shared server (primarysource.pdfcorpus.server) with the
gm spec. `primarysource mcp --collection gm` serves `mcp`; nothing here touches the network."""

from __future__ import annotations

from primarysource.gm.spec import SPEC
from primarysource.pdfcorpus.server import CorpusServer

SERVER = CorpusServer(SPEC)
mcp = SERVER.mcp


def main() -> None:
    """Serve over stdio (`primarysource mcp --collection gm` is the usual way)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
