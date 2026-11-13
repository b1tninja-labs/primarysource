"""The USB ID database: vendors, devices, classes and the other tables of the `usb.ids` file.

One collection, `usbids`. The file is published by the linux-usb.org USB ID Repository, which says its contents
"can be distributed under the terms of either the GNU General Public License (version 2 or later) or of the
3-clause BSD License" (docs/usbids.md has the URL and date). It is not USB-IF's text, and has nothing to do with
the `usb` collection's specifications except that the two answer questions about the same bus.

Standard library only. `primarysource usbids import` fetches the file (`importer.py`); `server.py` needs `mcp`
and is imported only when served (`primarysource mcp --collection usbids`); `primarysource usbids ...` runs
`cli.py`.
"""

from __future__ import annotations

from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.refs import Ref
from primarysource.registry import Collection
from primarysource.usbids.parse import format_ref, parse_ref


class UsbidsRefs:
    """The collection's `RefParser`. A ref names one entry, so the core's `Ref` carries the table in `doc` and the
    entry's ids in `section`: `usbids:1d6b:0002` is doc `usbids`, section `1d6b:0002`; `usbids:class/09/00` is
    doc `usbids`, section `class/09/00`."""

    def parse(self, text: str) -> Ref:
        section, key = parse_ref(text)
        return Ref("usbids", ":".join(key) if section == "vendor" else f"{section}/" + "/".join(key))

    def format(self, ref: Ref) -> str:
        if ref.doc not in (None, "usbids") or ref.section is None or ref.para or ref.anchor or ref.lines:
            raise LibError(f"not a usbids ref: {ref!r}", "a usbids ref is a doc `usbids` and a section only")
        section, key = parse_ref(ref.section)
        return format_ref(section, key)


COLLECTION = Collection(
    name="usbids",
    title="USB ID Database (usb.ids)",
    prefix="usbids_",
    unit=Unit.BLOCK,
    grammar=UsbidsRefs(),
    server="primarysource.usbids.server:server",
    cli="primarysource.usbids.cli:main",
)
"""Refs name one entry, not a section of a document, so they do not fit `RefGrammar` (`<doc>§<section>`);
`UsbidsRefs` parses the spelling with `parse.parse_ref`:

    usbids:1d6b            a vendor            usbids:1d6b:0002      a device (vendor id : product id, hex)
    usbids:class/09        a class             usbids:class/09/00/02 class / subclass / protocol
    usbids:hut/01/002      a HID usage page and usage; also at/, hid/, item/, bias/, phy/, lang/, hcc/, vt/

`¶n` is not used: every entry is one line, and a result's `unit` is `line`."""

__all__ = ["COLLECTION"]
