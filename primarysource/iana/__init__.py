"""IANA protocol registries as a primarysource collection: `iana`.

The registries are structured XML under `https://www.iana.org/assignments/`, dedicated to the public domain
(CC0 1.0) by IANA and the IETF for the Protocol Registries; `docs/iana.md` has the terms, the format and the ref
grammar. Nothing is shipped: `primarysource iana import <name>` (at most one request a second) fetches files into
`$PRIMARYSOURCE_HOME/iana/`.

Importing this package needs only the standard library; `mcp` is imported by `server.py` when the collection is
served (`primarysource mcp --collection iana`). `primarysource iana ...` runs `cli.py`.
"""

from __future__ import annotations

from primarysource.iana.reader import DOC, GRAMMAR
from primarysource.model import Unit
from primarysource.registry import Collection

COLLECTION = Collection(
    name="iana",
    title="IANA protocol registries (assignments)",
    prefix="iana_",
    unit=Unit.BLOCK,
    grammar=GRAMMAR,
    server="primarysource.iana.server:server",
    cli="primarysource.iana.cli:main",
)
"""Refs: `dns-parameters§dns-parameters-4` (a registry, by its IANA id), `bgp-parameters§bgp-parameters-2#3` (the
record whose value is 3), `bgp-parameters§bgp-parameters-2¶4` (the 4th record in file order). `§` names the
registry id, `#` a value, `¶n` the nth record. `dns-parameters#dns-parameters-4`, IANA's own URL fragment, names
the registry too. The unit is the record: each is one line of the registry's columns and its RFC citations."""

__all__ = ["COLLECTION", "DOC"]
