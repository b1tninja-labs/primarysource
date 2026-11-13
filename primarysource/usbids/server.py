"""MCP server for the usbids collection: `primarysource mcp --collection usbids`.

Imported only when served, so `mcp` (the `[mcp]` extra) is needed only then. Tools carry the `usbids_` prefix,
answer in text with the fixed footer, read the local database only (none writes or fetches), and turn a
`LibError` into an MCP tool error whose text names the remedy.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from primarysource import __version__
from primarysource.scaffold import add_tools
from primarysource.usbids import tools

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = (
    "The USB ID Database (usb.ids from the linux-usb.org USB ID Repository), imported by the user: vendor and "
    "product ids, device classes, HID usages, languages and other lookup tables. It names things; it is not a USB "
    "specification. Loop: usbids_search('<name>') -> usbids_lookup('<ref>'). Refs: 'usbids:1d6b' (vendor), "
    "'usbids:1d6b:0002' (device), 'usbids:class/09/00/02' (class/subclass/protocol), 'usbids:hut/01/002' (HID "
    "usage). usbids_classify('09', '00', '02') decodes a class code triple. The cite: footer line names the "
    "snapshot. If the database is not imported, the error says how."
)


def usbids_lookup(ref: str, start: int = 1, max_tokens: int = 2000) -> str:
    """Read one entry by ref with its parents and children. ref: 'usbids:1d6b' (a vendor, lists its devices),
    'usbids:1d6b:0002' (a device), 'usbids:class/09' (a class, lists subclasses), 'usbids:hut/01' (a HID usage
    page). A 'next: start=N' footer line means call again with start=N."""
    return tools.lookup(ref, start=start, max_tokens=max_tokens)


def usbids_search(text: str, section: str | None = None, limit: int = 20, start: int = 1) -> str:
    """Find entries whose name contains every word of text (a vendor's name counts for its devices). One line per
    hit: '<ref>  <name>'. section: vendor (vendors, devices, interfaces) | class | hut | lang | at | hid | item |
    bias | phy | hcc | vt. A 'next: start=N' footer line resumes."""
    return tools.search(text, section=section, limit=limit, start=start)


def usbids_classify(base_class: str, subclass: str | None = None, protocol: str | None = None) -> str:
    """Name a USB class code triple (hex, with or without 0x): usbids_classify('09', '00', '02')."""
    return tools.classify(base_class, subclass=subclass, protocol=protocol)


def usbids_sections() -> str:
    """The imported snapshot: version, date, sha256, source, licence and entry counts per section."""
    return tools.sections()


server = MCPServer("primarysource-usbids", version=__version__, instructions=INSTRUCTIONS)
add_tools(server, (usbids_lookup, usbids_search, usbids_classify, usbids_sections), annotations=READ_ONLY)
