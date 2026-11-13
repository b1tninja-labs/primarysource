"""A hardened XML parser for Broadband Forum data-model files (stdlib `xml.etree` over expat, nothing else).

The data-model XML is third-party text, so the parser is configured to be unable to do anything but build a tree:
- a document type declaration of any kind is refused (no DTD, so no internal or external entity can be declared:
  no billion-laughs expansion, no external file or URL read, no parameter entities); an `&name;` reference to
  anything but the five predefined entities and character references is an error;
- XInclude and XSLT are never processed (`ElementTree` has no such step), and no network or file is opened;
- bounds: input size, element count, nesting depth and attribute count are capped, and a document over a bound
  is refused, not truncated;
- namespace prefixes are dropped from element names and `xmlns`/prefixed attributes are ignored, because the BBF
  files qualify only the root (`dm:document`).

This stands in for the shared hardened XML decision owned by devicespy (FANOUT-BRIEF, organisation decisions).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - only `Element` objects are built, by the code below
from xml.parsers import expat  # noqa: S406 - hardened below: DOCTYPE refused, no entities, bounded

from primarysource.errors import LibError

MAX_BYTES = 16 * 1024 * 1024
MAX_ELEMENTS = 1_500_000
MAX_DEPTH = 64
MAX_ATTRIBUTES = 64
_DOCTYPE = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)", re.IGNORECASE)


def _local(name: str) -> str:
    return name.rpartition(":")[2]


def parse(data: bytes) -> ET.Element:
    """The root element of `data`, or a `LibError`. Never resolves an entity or reads outside `data`.

    Uses expat directly with a small tree builder instead of `ET.XMLParser`, so every handler that could be
    reached (doctype, entity declaration, external entity, parameter entity) is explicitly set to refuse."""
    if len(data) > MAX_BYTES:
        raise LibError(f"XML is {len(data)} bytes, over the {MAX_BYTES} byte bound", "")
    if _DOCTYPE.search(data):
        raise LibError("the XML has a document type declaration", "data-model files have none; refusing to parse")

    def refuse(*_: object) -> None:
        raise LibError("the XML has a document type declaration", "data-model files have none; refusing to parse")

    def refuse_external(context: str, base: str | None, system: str | None, public: str | None) -> int:
        refuse()
        return 0

    stack: list[ET.Element] = []
    roots: list[ET.Element] = []
    count = 0

    def start(tag: str, attrs: dict[str, str]) -> None:
        nonlocal count
        count += 1
        if len(stack) >= MAX_DEPTH or count > MAX_ELEMENTS or len(attrs) > MAX_ATTRIBUTES:
            raise LibError("the XML exceeds the parser's bounds", "this is not a Broadband Forum data-model file")
        element = ET.Element(_local(tag), {k: v for k, v in attrs.items() if ":" not in k and k != "xmlns"})
        if stack:
            stack[-1].append(element)
        elif roots:
            raise LibError("the XML has more than one root element", "")
        else:
            roots.append(element)
        stack.append(element)

    def end(_tag: str) -> None:
        stack.pop()

    def text(chunk: str) -> None:
        if not stack:
            return
        top = stack[-1]
        if len(top):
            last = top[-1]
            last.tail = (last.tail or "") + chunk
        else:
            top.text = (top.text or "") + chunk

    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse_external
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except LibError:
        raise
    except (expat.ExpatError, ValueError, RecursionError) as exc:
        raise LibError(
            f"the XML is not well formed: {exc}", "re-import the file; the pinned one is well formed"
        ) from exc
    if not roots:
        raise LibError("the XML has no root element", "")
    return roots[0]
