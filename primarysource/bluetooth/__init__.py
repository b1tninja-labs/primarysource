"""Bluetooth specifications from the catalog at bluetooth.com/specifications/specs/.

`primarysource bluetooth fetch` stores the catalog. `primarysource bluetooth sync` downloads each row's HTML
book and indexes it under `$PRIMARYSOURCE_HOME/bluetooth/`. The text is not redistributed with this package.
`docs/bluetooth.md` is the user-facing description.
"""

from __future__ import annotations

from primarysource.bluetooth.catalogue import DOC, SECTION
from primarysource.model import Unit
from primarysource.refs import Ref, RefGrammar
from primarysource.registry import Collection


class _Refs:
    """`library.parse_ref`, imported on first use so the collection loads without its reader."""

    _grammar = RefGrammar(DOC, SECTION)

    def parse(self, text: str) -> Ref:
        from primarysource.bluetooth.library import parse_ref

        return parse_ref(text)

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)


BLUETOOTH = Collection(
    name="bluetooth",
    title="Bluetooth specifications",
    prefix="bluetooth_",
    unit=Unit.BLOCK,
    grammar=_Refs(),
    server="primarysource.bluetooth.server:server",
    cli="primarysource.bluetooth.cli:main",
)
"""Refs: `bluetooth:battery-service§1.1¶2`. `§` is a section number; in the Core Specification it is
`volume.part.section`, as in `4.E.1`. `¶n` is the nth block of that section."""

__all__ = ["BLUETOOTH", "DOC", "SECTION"]
