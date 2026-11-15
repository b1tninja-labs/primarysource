"""MCP server for the gm collection: `primarysource mcp --collection gm`. Built by `localpdf.server`."""

from __future__ import annotations

from primarysource.gm import SPEC
from primarysource.localpdf.server import build_server

server = build_server(SPEC)
