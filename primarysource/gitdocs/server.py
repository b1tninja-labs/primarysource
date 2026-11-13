"""The MCP server for `gitdocs` (`primarysource mcp --collection gitdocs`). Imports `mcp` when this module loads."""

from __future__ import annotations

from primarysource.gitdocs.catalogue import SPEC
from primarysource.pkgdocs.serving import build_server

server = build_server(SPEC)
