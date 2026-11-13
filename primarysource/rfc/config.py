"""Paths, network policy and official source constants.

All URLs point at RFC Editor first-party infrastructure (rfc-editor.org),
the authoritative publisher/archive of the RFC Series for all five streams.
See RFC 9280 (RFC Editor Model v3), RFC 4714, RFC 7841.

Where the library lives: $RFCLIB_HOME if set, else the platform's per-user
data directory (platformdirs: %LOCALAPPDATA%\\rfclib on Windows, not
roaming, since the library is gigabytes; $XDG_DATA_HOME/rfclib or
~/.local/share/rfclib on Linux; ~/Library/Application Support/rfclib on
macOS). Never the working directory: MCP clients start servers from
wherever they like, so a cwd-relative home would silently point every
session at a different, empty library.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from primarysource.errors import LibError

from . import __version__

BASE_URL = "https://www.rfc-editor.org"
MANIFEST_URL = f"{BASE_URL}/rfc-index.xml"
MANIFEST_XSD_URL = f"{BASE_URL}/rfc-index.xsd"
RSS_URL = f"{BASE_URL}/rfcrss.xml"
ATOM_URL = f"{BASE_URL}/rfcatom.xml"
RSYNC_HOST = "rsync.rfc-editor.org"
RSYNC_DOC_URL = f"{BASE_URL}/series/rfc-download/"

USER_AGENT = f"rfclib/{__version__} (local RFC library sync; polite bulk fetch)"

NETWORK_MODES = ("auto", "on-demand", "offline")


def _default_home() -> Path:
    # RFCLIB_HOME, else $PRIMARYSOURCE_HOME/rfc, else an existing per-user
    # rfclib library, else the per-user primarysource/rfc
    # (primarysource.home.collection_home).
    from primarysource.home import collection_home
    return collection_home("rfc", legacy_app="rfclib").expanduser()


def legacy_home() -> Path | None:
    """A pre-platformdirs library in ./data (the old default), if one is
    sitting in the working directory and RFCLIB_HOME is not set: the CLI
    points at it instead of silently starting an empty library."""
    if os.environ.get("RFCLIB_HOME"):
        return None
    old = Path.cwd() / "data"
    if (old / "rfclib.db").is_file() and old.resolve() != \
            _default_home().resolve():
        return old
    return None


class NetworkDisabled(LibError, RuntimeError):
    """A fetch was needed but RFCLIB_NETWORK=offline (or read-only mode)
    forbids it. `action` says what a human runs to get the document in."""


def read_only() -> bool:
    """RFCLIB_READONLY=1 (or `rfclib mcp --read-only`): this process must not
    write the library. The MCP server then opens the database read-only and
    never fetches, so a shared HTTP server stays the only writer."""
    return any(
        (os.environ.get(var) or "").strip().lower() in ("1", "true", "yes", "on")
        for var in ("RFCLIB_READONLY", "PRIMARYSOURCE_READONLY"))


def network_mode() -> str:
    """RFCLIB_NETWORK: auto (default: fetch documents on demand, refresh the
    catalog when stale) | on-demand (fetch only when a document is asked
    for) | offline (never touch the network; answer from the cache).
    A read-only process is always offline: a fetch would have to be stored."""
    if read_only():
        return "offline"
    mode = (os.environ.get("RFCLIB_NETWORK") or "auto").strip().lower()
    return mode if mode in NETWORK_MODES else "auto"


def require_network(what: str) -> None:
    if read_only():
        raise NetworkDisabled(
            f"{what} is not in this library and this server is read-only "
            "(RFCLIB_READONLY)", "ask the shared rfclib server for it",
            "rfclib sync (without RFCLIB_READONLY)")
    if network_mode() == "offline":
        raise NetworkDisabled(
            f"{what} is not available locally and RFCLIB_NETWORK=offline "
            "forbids fetching it", "",
            "rfclib sync while online, or unset RFCLIB_NETWORK")


@dataclass(frozen=True)
class Paths:
    """Layout of the local library. Override the root with RFCLIB_HOME.

    home/
      rfclib.db        SQLite index (metadata, relations, file inventory)
      meta/            rfc-index.xml manifest copy, subject page cache
      mirror/          document files, rfc-editor layout (rfc/, bcp/, ...)
      models/          embedding model, loaded offline
    """

    home: Path

    @classmethod
    def default(cls) -> "Paths":
        return cls(_default_home())

    @property
    def db(self) -> Path:
        return self.home / "rfclib.db"

    @property
    def meta(self) -> Path:
        return self.home / "meta"

    @property
    def manifest_xml(self) -> Path:
        return self.meta / "rfc-index.xml"

    @property
    def mirror(self) -> Path:
        return self.home / "mirror"

    @property
    def models(self) -> Path:
        return self.home / "models"

    def ensure(self) -> "Paths":
        for p in (self.home, self.meta, self.mirror):
            p.mkdir(parents=True, exist_ok=True)
        return self
