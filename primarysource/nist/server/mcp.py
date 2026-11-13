"""MCP server for the local NIST publications: the shared server (primarysource.pdfcorpus.server) with the
nist spec. `primarysource mcp --collection nist` serves `mcp`."""

from __future__ import annotations

from primarysource.nist.spec import SPEC
from primarysource.pdfcorpus.server import CorpusServer

SERVER = CorpusServer(SPEC)
mcp = SERVER.mcp


def main() -> None:
    """Serve over stdio (`primarysource mcp --collection nist` is the usual way)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
