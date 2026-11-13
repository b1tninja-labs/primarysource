"""`debpolicy`: Debian Policy and the dpkg manual pages, pinned releases, read as reStructuredText and POD.
Served under `debpolicy_`.

Stdlib only. `mcp` is imported by `server.py` when a server is built; `primarysource debpolicy ...` runs `cli.py`.
`docs/debpolicy.md` is the description; `catalogue.py` holds the pin, the licence and the build.
"""

from __future__ import annotations

from primarysource.debpolicy.catalogue import SPEC
from primarysource.pkgdocs.runtime import make_collection

COLLECTION = make_collection(SPEC, "primarysource.debpolicy")
"""Refs: `debpolicy:5.6.1`; see `pkgdocs.runtime`."""

__all__ = ["COLLECTION", "SPEC"]
