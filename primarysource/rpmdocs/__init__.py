"""`rpmdocs`: rpm's manual and manual pages, a pinned release, read as Markdown and scdoc. Served under `rpmdocs_`.

Stdlib only. `mcp` is imported by `server.py` when a server is built; `primarysource rpmdocs ...` runs `cli.py`.
`docs/rpmdocs.md` is the description; `catalogue.py` holds the pin, the licence and the build.
"""

from __future__ import annotations

from primarysource.pkgdocs.runtime import make_collection
from primarysource.rpmdocs.catalogue import SPEC

COLLECTION = make_collection(SPEC, "primarysource.rpmdocs")
"""Refs: `rpmdocs:format_v6§Header`; see `pkgdocs.runtime`."""

__all__ = ["COLLECTION", "SPEC"]
