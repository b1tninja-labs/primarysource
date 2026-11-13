"""`pms`: the Gentoo Package Manager Specification, a pinned EAPI release, read from its LaTeX source.
Served under `pms_`.

Stdlib only. `mcp` is imported by `server.py` when a server is built; `primarysource pms ...` runs `cli.py`.
`docs/pms.md` is the description; `catalogue.py` holds the pin, the licence and the build.
"""

from __future__ import annotations

from primarysource.pkgdocs.runtime import make_collection
from primarysource.pms.catalogue import SPEC

COLLECTION = make_collection(SPEC, "primarysource.pms")
"""Refs: `pms:pms§Ebuild-defined variables`; see `pkgdocs.runtime`."""

__all__ = ["COLLECTION", "SPEC"]
