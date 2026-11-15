"""The ref parser of a local-PDF collection: `gm:17OBDG01-hybrid§p12¶3`.

The document is the collection's id for a file, `§` a section (a bookmarked clause or a page, `p12`) and `¶n` the
nth unit of that section's span. The collection's own prefix (`gm:`) is accepted and dropped.
"""

from __future__ import annotations

import re

from primarysource import cursor
from primarysource.errors import LibError
from primarysource.localpdf.spec import DOC_PATTERN, SECTION_PATTERN, LocalPdfSpec
from primarysource.refs import Ref, RefGrammar


class LocalRefs:
    """`RefParser` for one local-PDF collection."""

    def __init__(self, spec: LocalPdfSpec) -> None:
        self._spec = spec
        self._grammar = RefGrammar(DOC_PATTERN, SECTION_PATTERN)
        self._prefix = re.compile(rf"^{re.escape(spec.name)}:", re.IGNORECASE)

    def parse(self, text: str) -> Ref:
        body = self._prefix.sub("", text.strip(), count=1)
        body, doc_para = cursor.split_doc_para(body)
        ref = self._grammar.parse(body)
        if doc_para is not None:
            ref = Ref(ref.doc, None, doc_para, None, None)
        name = self._spec.name
        if ref.lines is not None or ref.anchor is not None:
            raise LibError(
                f"not a {name} ref: {text!r}", f"{name} refs are <doc>[§section][¶n], e.g. {self._spec.ref_example}"
            )
        if ref.doc is None:
            raise LibError(f"not a {name} ref: {text!r}", f"start with a document id, e.g. {self._spec.ref_example}")
        return ref

    def format(self, ref: Ref) -> str:
        return self._grammar.format(ref)
