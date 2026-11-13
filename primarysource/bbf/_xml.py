"""The bbf collection's XML reader: the core's hardened `primarysource.readers.xml` with bbf's bounds and names.

The parser moved to the core (`cl.reader_xml_hardened`); this wrapper keeps what the data-model reader and its
tests rely on:

- the bounds below, and a refusal over the byte bound or a structural bound in bbf's own words;
- namespace prefixes dropped from element names and namespaced attributes (`xsi:schemaLocation`) ignored, because
  the BBF files qualify only the root (`dm:document`). Prefixes are not resolved, so an undeclared one is not an
  error;
- processing instructions dropped, never acted on.

Everything else the core refuses is still refused: any document type declaration (so no entity, internal or
external, and no parameter entity), notations, encodings other than UTF-8, malformed input and a second root.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 - only `Element` objects are renamed here; parsing is the core's

from primarysource.errors import LibError
from primarysource.readers.xml import XmlRefused, XmlTooDeep, XmlTooLarge
from primarysource.readers.xml import parse as _parse

MAX_BYTES = 16 * 1024 * 1024
MAX_ELEMENTS = 1_500_000
MAX_DEPTH = 64
MAX_ATTRIBUTES = 64
MAX_ATTRIBUTE_LENGTH = 64 * 1024
HINT = "data-model files have none; refusing to parse"


def _local(name: str) -> str:
    return name.rpartition(":")[2]


def parse(data: bytes) -> ET.Element:
    """The root element of `data`, or a `LibError`. Never resolves an entity or reads outside `data`."""
    if len(data) > MAX_BYTES:
        raise LibError(f"XML is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    try:
        root = _parse(
            data,
            MAX_BYTES,
            max_depth=MAX_DEPTH,
            max_elements=MAX_ELEMENTS,
            max_attributes=MAX_ATTRIBUTES,
            max_attribute_length=MAX_ATTRIBUTE_LENGTH,
            max_text=MAX_BYTES,
            ignore_processing_instructions=True,
            namespaces=False,
            hint=HINT,
        )
    except (XmlTooDeep, XmlTooLarge) as exc:
        message = f"the XML exceeds the parser's bounds: {exc.reason}"
        raise LibError(message, "this is not a Broadband Forum data-model file") from exc
    except XmlRefused:
        raise
    for element in root.iter():
        element.tag = _local(element.tag)
        kept = {k: v for k, v in element.attrib.items() if ":" not in k and k != "xmlns"}
        if len(kept) != len(element.attrib):
            element.attrib = kept
    return root
