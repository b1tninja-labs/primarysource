"""The MCP server for `pms` (`primarysource mcp --collection pms`). Imports `mcp` when this module loads."""

from __future__ import annotations

from primarysource.pkgdocs.serving import build_server
from primarysource.pms.catalogue import SPEC

server = build_server(SPEC)
