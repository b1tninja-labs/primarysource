"""The iana collection's XML reader: the core's hardened `primarysource.readers.xml` with iana's bounds.

The parser moved to the core (`cl.reader_xml_hardened`). This wrapper keeps the signature the importer, the store
and their tests use, and the two choices iana makes on top of the core's defaults:

- processing instructions are dropped, not refused, because every IANA registry file opens with an
  `xml-stylesheet` and an `xml-model` instruction (nothing is ever fetched or executed for them);
- up to 600,000 elements, because the largest registries are that big.

Everything the core refuses is still refused: declarations, entities, notations, external references, encodings
other than UTF-8, and input over any bound. Names come out in ElementTree's `{namespace}local` form.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 - only the Element type; parsing is the core's hardened expat

from primarysource.readers.xml import XmlRefused
from primarysource.readers.xml import parse as _parse

__all__ = ["HINT", "XmlRefused", "parse"]

HINT = "the file is damaged or not a registry file; fetch it again"


def parse(
    raw: bytes,
    limit: int,
    *,
    max_depth: int = 32,
    max_elements: int = 600_000,
    max_attributes: int = 16,
    max_attribute_length: int = 4096,
    max_text: int = 1_000_000,
) -> ET.Element:
    """Parse `raw` into an Element, or raise `XmlRefused` (a `LibError`). The whole document is passed at once."""
    return _parse(
        raw,
        limit,
        max_depth=max_depth,
        max_elements=max_elements,
        max_attributes=max_attributes,
        max_attribute_length=max_attribute_length,
        max_text=max_text,
        ignore_processing_instructions=True,
        hint=HINT,
    )
