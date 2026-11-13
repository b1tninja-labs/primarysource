"""Read what `importer.import_pdf` stored for an 802 standard: its clause outline from the PDF's bookmarks.

Reading a clause's sentences (`802.1Q-2022§5.4¶2`) needs a clause segmenter over the extracted page text; that is
the core's planned `cl.segment_bookmarks` (itulib's walker), so it is a `[ ]` row (`ieee.ieee802_read`), not code
written twice here.
"""

from __future__ import annotations

import json
from pathlib import Path

from primarysource.errors import LibError
from primarysource.ieee import IEEE802
from primarysource.ieee.catalogue import edition
from primarysource.ieee.importer import INSTALL_RECORD, collection_home, normalise_designation
from primarysource.refs import Ref
from primarysource.render import render


def installed(designation: str, home: Path | None = None) -> Path:
    """The directory of an imported 802 standard, or a LibError that says how to import it."""
    pinned = edition("ieee802", normalise_designation(designation))
    root = collection_home("ieee802", home) / pinned.id
    if not (root / INSTALL_RECORD).is_file():
        raise LibError(
            f"{pinned.id} is not imported",
            f"obtain the PDF yourself from {pinned.page_url} (IEEE GET Program terms, see docs/ieee.md), then run "
            f"primarysource ieee802 import <file.pdf> {pinned.id}",
        )
    return root


def outline(designation: str, *, home: Path | None = None) -> str:
    """The PDF's bookmarks, indented by depth, with a ref for each numbered clause and its PDF page."""
    root = installed(designation, home)
    pinned = edition("ieee802", normalise_designation(designation))
    entries = json.loads((root / "outline.json").read_text(encoding="utf-8"))
    lines = []
    for entry in entries:
        ref = IEEE802.grammar.format(Ref(pinned.id, entry["clause"])) if entry["clause"] else ""
        where = f"p. {entry['page']}" if entry["page"] else "no page"
        parts = [entry["title"], ref, f"({where})"]
        lines.append("  " * (entry["depth"] - 1) + "  ".join(part for part in parts if part))
    body = "\n".join(lines) if lines else f"{pinned.id} has no bookmarks"
    return render(body, {"cite": f"{pinned.designations[0]}, {pinned.title}", "unit": IEEE802.unit})
