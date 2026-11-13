"""The MCP server for `rpmdocs` (`primarysource mcp --collection rpmdocs`). Imports `mcp` when this module loads."""

from __future__ import annotations

from primarysource.pkgdocs.serving import build_server
from primarysource.rpmdocs.catalogue import SPEC

server = build_server(SPEC)
