"""`pep`: Python Enhancement Proposals, a pinned commit of python/peps, read as reStructuredText. Served under `pep_`.

Stdlib only. `mcp` is imported by `server.py` when a server is built; `primarysource pep ...` runs `cli.py`.
`docs/pep.md` is the description; `catalogue.py` holds the pin, the licence and the build.
"""

from __future__ import annotations

from primarysource.pep.catalogue import SPEC
from primarysource.pkgdocs.runtime import make_collection

COLLECTION = make_collection(SPEC, "primarysource.pep")
"""Refs: `pep:440§Version scheme`; see `pkgdocs.runtime`."""

__all__ = ["COLLECTION", "SPEC"]
