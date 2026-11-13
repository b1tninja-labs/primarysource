"""Broadband Forum: the TR-181 and other CWMP/USP data models (XML) and Technical Reports such as TR-069.

Two sources in one collection, because one consumer (cwmp) needs both and a ref reads the same way:
- data-model XML from https://github.com/BroadbandForum/cwmp-data-models, pinned to one commit, BSD-3-Clause
  notice in every file (image layer allowed): `bbf:tr-181-2-22-0-ip§Device.IP.Interface.{i}.Enable`;
- Technical Report PDFs fetched by the user into a volume (TR-069 Amendment 6 Corrigendum 1 so far):
  `bbf:tr-069-1-6-1§3.5¶2`.

Reading XML needs only the standard library (hardened parser in `_xml.py`); importing a PDF needs `pypdf` (the
`[bbf]` extra). `docs/bbf.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection

BBF_DOC = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
"""A document by its Forum file stem: `tr-069-1-6-1` (a report), `tr-181-2-22-0-ip` (a data-model file)."""

BBF_SECTION = r"[^\s#¶§][^\s#¶§]*"
"""A report clause (`3.5`, `A.3.2.3`, a slug) or a data-model node (`Device.IP.Interface.{i}.Enable`,
`Device.Reboot()`, `Device.Boot!`, `Baseline:1`). No spaces, never `#`, `¶` or `§`."""


class _Refs:
    """The collection's ref parser: `library.parse_ref` (which also takes the `bbf:` prefix and refuses what the
    collection has no meaning for), imported on first use so the collection loads without its reader."""

    _grammar = RefGrammar(BBF_DOC, BBF_SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.bbf.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


BBF = Collection(
    name="bbf",
    title="Broadband Forum data models and Technical Reports (TR-069, TR-181)",
    prefix="bbf_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.bbf.server:server",
    cli="primarysource.bbf.cli:main",
)
"""Refs: `bbf:tr-069-1-6-1§3.5¶2` and `bbf:tr-181-2-22-0-ip§Device.IP.Interface.{i}.Enable¶1`. `§` names a report
clause by its number or a data-model node by its full path. `¶n` is the nth sentence of a report clause's span
(a PDF gives sentences) and the nth paragraph of a data-model node's description; every result's `unit:` footer
says which. The collection's declared unit is therefore `block`. The `bbf:` prefix is optional."""

__all__ = ["BBF", "BBF_DOC", "BBF_SECTION"]
