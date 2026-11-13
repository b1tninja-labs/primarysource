"""Run an MCP server on stdio or as one shared HTTP server: the transport switch every collection uses.

Lifted from rfclib's `rfclib mcp` (rfclib PR #1). stdio starts one server per client. http starts one long-lived
server that every client reaches by URL (MCP streamable HTTP at `/mcp`), stateless and with JSON responses, so a
restart loses no session. There is no authentication: the default bind is loopback, where the SDK checks the
Host header itself. A non-loopback bind gets the same check only when allowed hosts are named; without them it
warns, because anyone who can reach the port can use the server.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from typing import Any

from primarysource.errors import LibError

MCP_HTTP_PORT = 8765
LOOPBACK = ("127.0.0.1", "localhost", "::1")
TRANSPORTS = {"stdio": "stdio", "http": "http", "streamable-http": "http", "streamable_http": "http"}


def normalise_transport(transport: str) -> str:
    """`stdio` or `http`; the SDK's own spellings of streamable HTTP are accepted."""
    found = TRANSPORTS.get(transport.strip().lower())
    if found is None:
        raise LibError(f"unknown transport {transport!r}", "use --transport stdio or --transport http")
    return found


def transport_security(host: str, allowed_hosts: Sequence[str]) -> Any:
    """The DNS-rebinding settings for a bind address: None on loopback (the SDK enables its own check there),
    an allow-list when hosts are named, else None with a warning on stderr."""
    if host in LOOPBACK:
        return None
    if not allowed_hosts:
        print(
            f"warning: listening on {host} with no authentication and no Host check; anyone who can reach the "
            "port can use this server. Keep it behind a firewall or an authenticating reverse proxy.",
            file=sys.stderr,
        )
        return None
    from mcp.server.transport_security import TransportSecuritySettings

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(allowed_hosts),
        allowed_origins=[f"{scheme}://{h}" for h in allowed_hosts for scheme in ("http", "https")],
    )


def run(
    server: Any,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = MCP_HTTP_PORT,
    allowed_hosts: Sequence[str] = (),
) -> None:
    """Serve `server` (an `mcp.server.mcpserver.MCPServer`) until interrupted."""
    kind = normalise_transport(transport)
    # stdout is the JSON-RPC channel on stdio; per-request client logs would flood stderr either way
    for name in ("httpx", "httpcore", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if kind == "stdio":
        server.run(transport="stdio")
        return
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(host, allowed_hosts),
    )
