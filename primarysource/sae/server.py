"""MCP server for the sae collection: `primarysource mcp --collection sae`. Built by `localpdf.server`."""

from __future__ import annotations

from primarysource.localpdf.server import build_server
from primarysource.sae import SPEC

server = build_server(SPEC)
