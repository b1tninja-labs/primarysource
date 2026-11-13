"""`gitdocs`: git's Documentation/ tree, a pinned release, read as AsciiDoc and served under `gitdocs_`.

Stdlib only. `mcp` is imported by `server.py` when a server is built; `primarysource gitdocs ...` runs `cli.py`.
`docs/gitdocs.md` is the description; `catalogue.py` holds the pin, the licence and the build.
"""

from __future__ import annotations

from primarysource.gitdocs.catalogue import SPEC
from primarysource.pkgdocs.runtime import make_collection

COLLECTION = make_collection(SPEC, "primarysource.gitdocs")
"""Refs: `gitdocs:gitformat-pack@03b4152§pack-*.idx files have the following format`; see `pkgdocs.runtime`."""

__all__ = ["COLLECTION", "SPEC"]
