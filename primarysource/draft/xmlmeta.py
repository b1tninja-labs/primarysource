"""What the root element of a draft's submitted `.xml` says, read without parsing the rest.

The archive's `.xml` is the author's source: xml2rfc v2 (`<!DOCTYPE rfc SYSTEM "rfc2629.dtd">`, no `version`
attribute) or v3, with no `pn` ids and no section numbers. It is stored as the author's source and pinned, but
it is not segmented (segment.py says why), so all this module reads is the root start tag: the format version,
`docName`, `category`, `submissionType` and `ipr` (the licence legend, RFC 7991 Appendix A.1.1).

Reading only the first start tag is also the hardening. The rest of a v2 source can use entities the DTD defines
(`&nbsp;`) which a parser without the DTD cannot expand, and a hostile file can declare its own. So:

- any `<!ENTITY` or internal DTD subset is refused before a parser sees the bytes (no billion-laughs, no
  external entity, ever);
- the parser stops at the root start tag, and never fetches a DTD.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405  # internal subsets and entities are refused first; root tag only
from dataclasses import dataclass
from typing import Any

V2 = "v2"
V3 = "v3"
REFUSED = "refused"
UNPARSEABLE = "unparseable"

_INTERNAL_SUBSET = re.compile(rb"<!DOCTYPE[^>\[]*\[")
_MAX_ATTR = 200
_HEAD = 65536
_ROOT_TAG = re.compile(rb"<rfc(?=[\s/>])(?:[^>\"']|\"[^\"]*\"|'[^']*')*>")


@dataclass(frozen=True, slots=True)
class XmlInfo:
    """`state` is V2, V3, REFUSED or UNPARSEABLE; `why` says what was refused; the rest are the root's
    attributes (empty when absent)."""

    state: str
    ipr: str = ""
    doc_name: str = ""
    category: str = ""
    submission_type: str = ""
    why: str = ""


def inspect(data: bytes) -> XmlInfo:
    """The root element's facts, or a refusal that says why. Never raises on bad input."""
    if b"<!ENTITY" in data:
        return XmlInfo(REFUSED, why="declares entities")
    if _INTERNAL_SUBSET.search(data[:4096]):
        return XmlInfo(REFUSED, why="has an internal DTD subset")
    root = _ROOT_TAG.search(data[:_HEAD])
    if root is None:
        return XmlInfo(UNPARSEABLE, why=f"no <rfc> start tag in the first {_HEAD:,} bytes")
    parser: ET.XMLPullParser[Any] = ET.XMLPullParser(events=("start",))
    try:
        # only the bytes up to the end of the root start tag are fed: whatever follows (entities a DTD would
        # define, a hostile body) is never seen by the parser
        parser.feed(data[: root.end()])
        events: Any = parser.read_events()
        for event in events:
            element = event[1]
            attrs = {key: value[:_MAX_ATTR] for key, value in element.attrib.items()}
            return XmlInfo(
                V3 if attrs.get("version") == "3" else V2,
                ipr=attrs.get("ipr", ""),
                doc_name=attrs.get("docName", ""),
                category=attrs.get("category", ""),
                submission_type=attrs.get("submissionType", ""),
            )
    except ET.ParseError as exc:
        return XmlInfo(UNPARSEABLE, why=str(exc)[:100])
    return XmlInfo(UNPARSEABLE, why="no root element")
