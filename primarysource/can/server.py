"""MCP server for the can collection: `primarysource mcp --collection can`. Built by `localpdf.server`."""

from __future__ import annotations

from primarysource.can import SPEC
from primarysource.localpdf.server import build_server

server = build_server(SPEC)
