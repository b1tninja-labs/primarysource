"""The MCP server for `pep` (`primarysource mcp --collection pep`). Imports `mcp` when this module loads."""

from __future__ import annotations

from primarysource.pep.catalogue import SPEC
from primarysource.pkgdocs.serving import build_server

server = build_server(SPEC)
