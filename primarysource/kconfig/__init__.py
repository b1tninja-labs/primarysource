"""`kconfig`: the Kconfig language documents of the Linux kernel, a pinned release, read as reStructuredText.
Served under `kconfig_`.

Stdlib only. `mcp` is imported by `server.py` when a server is built; `primarysource kconfig ...` runs `cli.py`.
`docs/kconfig.md` is the description; `catalogue.py` holds the pin, the licence and the build.
"""

from __future__ import annotations

from primarysource.kconfig.catalogue import SPEC
from primarysource.pkgdocs.runtime import make_collection

COLLECTION = make_collection(SPEC, "primarysource.kconfig")
"""Refs: `kconfig:kconfig-language§Menu entries`; see `pkgdocs.runtime`."""

__all__ = ["COLLECTION", "SPEC"]
