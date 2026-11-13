"""C2SP: the Community Cryptography Specification Project's specifications (CC BY 4.0), as one collection.

The source is Markdown in https://github.com/C2SP/C2SP, pinned to one commit (`catalogue.json`) and imported with
`primarysource c2sp import`. Because the text is CC BY 4.0 it may also be placed in an image layer; the importer
itself only writes `$PRIMARYSOURCE_HOME/c2sp/<commit>/`. `docs/c2sp.md` is the user-facing description.

Importing this package needs only the standard library; `mcp` (the `[mcp]` extra) only when a collection is
served (`primarysource mcp --collection c2sp`). `primarysource c2sp ...` runs `cli.py`.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection

C2SP_DOC = r"[A-Za-z0-9][A-Za-z0-9-]*(?:@[0-9a-f]{7,40})?"
"""A specification by file name, case as in the repository, optionally pinned to a commit prefix:
`static-ct-api`, `tlog-tiles@09f3e51`, `BLAKE3`."""

C2SP_SECTION = r"[^#¶:§\s][^#¶:§]*"
"""A heading's text (`Log Entries`) or its slug (`log-entries`). May contain spaces, never `:`, `#`, `¶` or `§`."""


class _Refs:
    """The collection's ref parser: `library.parse_ref` (which also takes the `c2sp:` prefix and refuses what the
    collection has no meaning for), imported on first use so the collection loads without its reader."""

    _grammar = RefGrammar(C2SP_DOC, C2SP_SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.c2sp.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


C2SP = Collection(
    name="c2sp",
    title="C2SP specifications (Community Cryptography Specification Project)",
    prefix="c2sp_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.c2sp.server:server",
    cli="primarysource.c2sp.cli:main",
)
"""Refs: `c2sp:static-ct-api@09f3e51§Log Entries¶2`. `§` names a heading by its text or its slug; `¶n` counts
blank-line-separated blocks (a paragraph, a list, a fenced code block) in that heading's span, subsections included,
its own heading excluded. The `c2sp:` prefix and the `@commit` are optional."""

__all__ = ["C2SP", "C2SP_DOC", "C2SP_SECTION"]
