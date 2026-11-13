"""A hardened XML reader for registry files, built on `xml.parsers.expat`.

Adapted from the approach of devicespy's `xmlsafe` (read, not imported: a collection here depends on nothing
outside this package). It refuses rather than defends:

- any document type declaration, entity or parameter-entity declaration, notation or external reference, so no
  entity can be declared and expansion attacks are impossible;
- any declared encoding other than UTF-8, and input that looks like UTF-16 or UTF-32;
- input over `limit` bytes, nesting over `max_depth`, more than `max_elements` elements, more than
  `max_attributes` attributes on one element, an attribute value over `max_attribute_length` characters, and
  text in one element over `max_text`.

Processing instructions are dropped, not refused, because every IANA registry file opens with an
`xml-stylesheet` and an `xml-model` instruction. Nothing is ever fetched or executed for them.
Names come out in ElementTree's `{namespace}local` form.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 - only used to build elements; parsing is expat with DTDs refused
from typing import NoReturn
from xml.parsers import expat

from primarysource.errors import LibError

_SEP = "}"


class XmlRefused(LibError):
    """The document was refused; the message says why in one short phrase."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"XML refused: {reason}", "the file is damaged or not a registry file; fetch it again")
        self.reason = reason


def _qname(name: str) -> str:
    if _SEP in name:
        uri, local = name.rsplit(_SEP, 1)
        return "{" + uri + "}" + local
    return name


class _Builder:
    def __init__(
        self, max_depth: int, max_elements: int, max_attributes: int, max_attribute_length: int, max_text: int
    ):
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.max_attributes = max_attributes
        self.max_attribute_length = max_attribute_length
        self.max_text = max_text
        self.stack: list[ET.Element] = []
        self.root: ET.Element | None = None
        self.count = 0
        self.tail_of: ET.Element | None = None

    def refuse(self, *_args: object) -> NoReturn:
        raise XmlRefused("document type declarations, entities and notations are not accepted")

    def xml_decl(self, _version: str, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.lower() not in ("utf-8", "utf8"):
            raise XmlRefused("only UTF-8 is accepted, the document declares " + encoding)

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if len(self.stack) >= self.max_depth:
            raise XmlRefused(f"nesting deeper than {self.max_depth}")
        self.count += 1
        if self.count > self.max_elements:
            raise XmlRefused(f"more than {self.max_elements} elements")
        if len(attrs) > self.max_attributes:
            raise XmlRefused(f"more than {self.max_attributes} attributes on one element")
        for value in attrs.values():
            if len(value) > self.max_attribute_length:
                raise XmlRefused(f"an attribute value is longer than {self.max_attribute_length}")
        element = ET.Element(_qname(name), {_qname(k): v for k, v in attrs.items()})
        if self.stack:
            self.stack[-1].append(element)
        else:
            self.root = element
        self.stack.append(element)
        self.tail_of = None

    def end(self, _name: str) -> None:
        self.tail_of = self.stack.pop()

    def data(self, text: str) -> None:
        if self.tail_of is not None:
            self.tail_of.tail = (self.tail_of.tail or "") + text
            if len(self.tail_of.tail) > self.max_text:
                raise XmlRefused(f"text longer than {self.max_text}")
        elif self.stack:
            top = self.stack[-1]
            top.text = (top.text or "") + text
            if len(top.text) > self.max_text:
                raise XmlRefused(f"text longer than {self.max_text}")


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
    if limit < 0:
        raise ValueError("limit must not be negative")
    if len(raw) > limit:
        raise XmlRefused(f"{len(raw):,} bytes exceeds the limit of {limit:,}")
    if not raw:
        raise XmlRefused("empty document")
    head = bytes(raw[:4])
    if head[:2] in (b"\xfe\xff", b"\xff\xfe") or b"\x00" in head:
        raise XmlRefused("only UTF-8 is accepted, the input looks like UTF-16 or UTF-32")
    builder = _Builder(max_depth, max_elements, max_attributes, max_attribute_length, max_text)
    parser = expat.ParserCreate(None, _SEP)
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = builder.refuse
    parser.EntityDeclHandler = builder.refuse
    parser.ExternalEntityRefHandler = builder.refuse
    parser.NotationDeclHandler = builder.refuse
    parser.XmlDeclHandler = builder.xml_decl
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(bytes(raw), True)
    except XmlRefused:
        raise
    except expat.ExpatError as error:
        raise XmlRefused("not well-formed XML: " + expat.ErrorString(error.code)) from None
    if builder.root is None:
        raise XmlRefused("no root element")
    return builder.root
