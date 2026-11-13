"""MCP server for the cavp collection: `primarysource mcp --collection cavp`.

Tools are prefixed `cavp_`, answer in text with the fixed footer, and turn a `LibError` into a tool error naming
the remedy. Read-only, local files only.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.cavp import tools
from primarysource.cavp.paths import open_store
from primarysource.scaffold import add_tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)
INSTRUCTIONS = (
    "NIST cryptographic test vectors (CAVP .rsp, ACVP JSON) the user imported, each pinned by sha256. "
    "cavp_sets() lists them as refs; cavp_groups('nist:cavp/ecdsa/SigVer.rsp') lists a set's groups; "
    "cavp_read('nist:cavp/ecdsa/SigVer.rsp#[P-256,SHA-256]/3') reads one case in full; cavp_find looks a case up "
    "by a field value (a message, a key, a signature). ACVP refs use the tgId and tcId: "
    "'nist:acvp/ECDSA-SigVer-1.0#1/3'. The cite: footer line is the citation. If nothing is imported the error "
    "says how."
)


def cavp_sets(query: str | None = None, limit: int = 50) -> str:
    """List imported vector sets, one ref per line with algorithm, mode and counts. query filters by id,
    algorithm or mode."""
    return tools.sets(open_store(), query, limit)


def cavp_groups(set_ref: str, start: int = 0, max_tokens: int = 2000) -> str:
    """List a set's groups as refs with their case counts and parameters. set_ref: 'nist:cavp/ecdsa/SigVer.rsp'.
    A 'next: start=N' footer line means call again with start=N (a 0-based offset)."""
    return tools.groups(open_store(), set_ref, start, max_tokens)


def cavp_read(ref: str, max_tokens: int = 2000) -> str:
    """Read by ref: a set ('nist:cavp/ecdsa/SigVer.rsp'), a group ('...#[P-256,SHA-256]', values shortened) or one
    case in full ('...#[P-256,SHA-256]/3'). A 'next: <ref>' footer line is the ref that reads the next page: pass
    it back as ref."""
    return tools.read(open_store(), ref, max_tokens)


def cavp_find(
    set_ref: str,
    field: str,
    value: str,
    group: str | None = None,
    start: int = 0,
    max_tokens: int = 2000,
) -> str:
    """Find cases in a set whose field equals value (hex compared without case or 0x), e.g. field='Msg'.
    Returns refs. field may be 'expected.<name>' for an ACVP answer. A 'next: start=N' footer line means call
    again with start=N (a 0-based offset)."""
    return tools.find(open_store(), set_ref, field, value, group, start, max_tokens)


def cavp_cite(ref: str) -> str:
    """The citation for a ref: algorithm, mode, source URL, pinned sha256, and NIST's credit line."""
    return tools.cite(open_store(), ref)


cavp_server = MCPServer("primarysource-cavp", version=__version__, instructions=INSTRUCTIONS)
add_tools(cavp_server, (cavp_sets, cavp_groups, cavp_read, cavp_find, cavp_cite), annotations=READ_ONLY)
