"""The MCP server for `kconfig` (`primarysource mcp --collection kconfig`). Imports `mcp` when this module loads."""

from __future__ import annotations

from primarysource.kconfig.catalogue import SPEC
from primarysource.pkgdocs.serving import build_server

server = build_server(SPEC)
