"""The one hardened XML reader (`cl.reader_xml_hardened`), built on `xml.parsers.expat` and nothing else.

Three copies were compared: `primarysource/iana/xmlsafe.py`, `primarysource/bbf/_xml.py` and devicespy's
`devicespy/xmlsafe.py` (read, not imported; devicespy commit e26c820). This keeps the strictest behaviour of each:
devicespy's design and typed refusals, iana's text bound, bbf's scan for declarations before parsing. The iana and
bbf modules are now thin wrappers over this one that keep their own bounds and messages.

It refuses rather than defends:

- any document type declaration, entity or parameter-entity declaration, notation or external reference, so no
  entity can be declared, expansion attacks are impossible and nothing is ever fetched. The raw bytes are scanned
  for `<!DOCTYPE`, `<!ENTITY`, `<!ELEMENT`, `<!ATTLIST` and `<!NOTATION` before expat sees them (also in a
  UTF-16 or UTF-32 decoding, so a declaration hidden by the encoding is named as one), and every expat handler
  that a declaration would reach refuses too;
- any processing instruction other than the XML declaration, unless `ignore_processing_instructions` is set, in
  which case they are dropped and never acted on (IANA registry files open with two);
- any declared encoding other than UTF-8, and input that looks like UTF-16 or UTF-32;
- input over `limit` bytes (checked before a parser exists), nesting over `max_depth`, more than `max_elements`
  elements, more than `max_attributes` attributes on one element, an attribute value over
  `max_attribute_length` characters, and text or a tail in one element over `max_text` characters;
- empty, truncated and malformed input, an undefined entity and a second root element.

XInclude and XSLT are never processed: ElementTree has no such step and only `Element` objects are built here.
Every refusal is an `XmlRefused`, which is a `LibError` with a hint, in one of four kinds: `XmlTooLarge`,
`XmlTooDeep`, `XmlForbidden`, `XmlMalformed`.

Names come out in ElementTree's `{namespace}local` form, unless `namespaces=False`, when they are the raw
qualified names (`dm:document`) and an undeclared prefix is not an error.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - only used to build elements; parsing is expat with DTDs refused
from typing import NoReturn
from xml.parsers import expat  # noqa: S406 - hardened below: declarations refused, no entities, bounded

from primarysource.errors import LibError

__all__ = [
    "DEFAULT_HINT",
    "XmlForbidden",
    "XmlMalformed",
    "XmlRefused",
    "XmlTooDeep",
    "XmlTooLarge",
    "localname",
    "parse",
]

DEFAULT_HINT = "the file is damaged or not the expected document; fetch or import it again"
_SEP = "}"
_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)", re.IGNORECASE)
_DECLARATION_TEXT = re.compile(r"<!\s*(?:DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)", re.IGNORECASE)
_WIDE_CODECS = ("utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be")
_FORBIDDEN_DECLARATIONS = "document type declarations, entities and notations are not accepted"


class XmlRefused(LibError):  # noqa: N818 - the name is the contract, as in devicespy
    """The document was refused. `reason` says why in one short phrase; the message is `XML refused: <reason>`."""

    def __init__(self, reason: str, hint: str = DEFAULT_HINT) -> None:
        super().__init__(f"XML refused: {reason}", hint)
        self.reason = reason


class XmlTooLarge(XmlRefused):
    """A size bound was exceeded: bytes, elements, attributes, attribute length or text length."""


class XmlTooDeep(XmlRefused):
    """Element nesting went past `max_depth`."""


class XmlForbidden(XmlRefused):
    """A construct this reader never accepts: a declaration, an entity, a processing instruction, an encoding."""


class XmlMalformed(XmlRefused):
    """Not well-formed XML, including empty and truncated input."""


def _qname(name: str) -> str:
    # expat with a namespace separator yields "uri}local" (the local part cannot contain it).
    if _SEP in name:
        uri, local = name.rsplit(_SEP, 1)
        return "{" + uri + "}" + local
    return name


def localname(tag: str) -> tuple[str, str]:
    """Split an ElementTree name `{namespace}local` into `(namespace, local)`; no namespace gives `("", name)`."""
    if tag.startswith("{"):
        uri, sep, local = tag[1:].partition("}")
        if sep:
            return uri, local
    return "", tag


class _Builder:
    def __init__(
        self,
        hint: str,
        max_depth: int,
        max_elements: int,
        max_attributes: int,
        max_attribute_length: int,
        max_text: int,
    ) -> None:
        self.hint = hint
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
        raise XmlForbidden(_FORBIDDEN_DECLARATIONS, self.hint)

    def refuse_pi(self, *_args: object) -> NoReturn:
        raise XmlForbidden("processing instructions are not accepted", self.hint)

    def xml_decl(self, _version: str, encoding: str | None, _standalone: int) -> None:
        if encoding is not None and encoding.lower() not in ("utf-8", "utf8"):
            raise XmlForbidden("only UTF-8 is accepted, the document declares " + encoding, self.hint)

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if len(self.stack) >= self.max_depth:
            raise XmlTooDeep(f"nesting deeper than {self.max_depth}", self.hint)
        self.count += 1
        if self.count > self.max_elements:
            raise XmlTooLarge(f"more than {self.max_elements} elements", self.hint)
        if len(attrs) > self.max_attributes:
            raise XmlTooLarge(f"more than {self.max_attributes} attributes on one element", self.hint)
        for value in attrs.values():
            if len(value) > self.max_attribute_length:
                raise XmlTooLarge(f"an attribute value is longer than {self.max_attribute_length}", self.hint)
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
                raise XmlTooLarge(f"text longer than {self.max_text}", self.hint)
        elif self.stack:
            top = self.stack[-1]
            top.text = (top.text or "") + text
            if len(top.text) > self.max_text:
                raise XmlTooLarge(f"text longer than {self.max_text}", self.hint)


def _looks_wide(head: bytes) -> bool:
    return head[:2] in (b"\xfe\xff", b"\xff\xfe") or b"\x00" in head


def _declares_in_wide_text(raw: bytes) -> bool:
    return any(_DECLARATION_TEXT.search(raw.decode(codec, errors="ignore")) for codec in _WIDE_CODECS)


def parse(
    raw: bytes,
    limit: int,
    *,
    max_depth: int = 32,
    max_elements: int = 50_000,
    max_attributes: int = 16,
    max_attribute_length: int = 4096,
    max_text: int = 1_000_000,
    ignore_processing_instructions: bool = False,
    namespaces: bool = True,
    hint: str = DEFAULT_HINT,
) -> ET.Element:
    """Parse `raw` into its root Element, or raise `XmlRefused` (a `LibError` carrying `hint`).

    `limit` is the largest acceptable `len(raw)` and is checked before any parsing. The whole document is passed
    at once. The defaults are the strictest any of the three source copies used; a caller with larger documents
    passes its own bounds. The root returned is never a placeholder: every refusal raises."""
    if not isinstance(raw, bytes | bytearray | memoryview):
        raise TypeError("raw must be bytes")
    if limit < 0:
        raise ValueError("limit must not be negative")
    if len(raw) > limit:
        raise XmlTooLarge(f"{len(raw):,} bytes exceeds the limit of {limit:,}", hint)
    data = bytes(raw)
    if not data:
        raise XmlMalformed("empty document", hint)
    if _DECLARATION.search(data):
        raise XmlForbidden(_FORBIDDEN_DECLARATIONS, hint)
    if _looks_wide(data[:4]):
        if _declares_in_wide_text(data):
            raise XmlForbidden(_FORBIDDEN_DECLARATIONS, hint)
        raise XmlForbidden("only UTF-8 is accepted, the input looks like UTF-16 or UTF-32", hint)
    builder = _Builder(hint, max_depth, max_elements, max_attributes, max_attribute_length, max_text)
    parser = expat.ParserCreate(None, _SEP) if namespaces else expat.ParserCreate()
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = builder.refuse
    parser.EntityDeclHandler = builder.refuse
    parser.ExternalEntityRefHandler = builder.refuse
    parser.NotationDeclHandler = builder.refuse
    if not ignore_processing_instructions:
        parser.ProcessingInstructionHandler = builder.refuse_pi
    parser.XmlDeclHandler = builder.xml_decl
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except XmlRefused:
        raise
    except expat.ExpatError as error:
        raise XmlMalformed("not well-formed XML: " + expat.ErrorString(error.code), hint) from None
    except (ValueError, RecursionError) as error:
        raise XmlMalformed(f"not well-formed XML: {type(error).__name__}", hint) from None
    if builder.root is None:
        raise XmlMalformed("no root element", hint)
    return builder.root
