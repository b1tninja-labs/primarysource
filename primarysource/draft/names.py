"""What a draft's name and revision look like, and how a ref's document part is split into the two.

The datatracker names a draft `draft-<words>` in lowercase letters, digits and hyphens, and a revision is two
digits, `00` to `99`, appended with a hyphen: `draft-ietf-sidrops-8210bis-17`. A trailing `-NN` of exactly two
digits is read as the revision, which is how the datatracker itself reads it; a draft whose own name ends in two
digits therefore has to be written with its revision (`draft-foo-bar-12-00`) to be unambiguous.

Every name that reaches a URL or a path passes `parse_name` or `split_doc` first, so none of `/`, `..`, `%`, a
newline or an uppercase letter gets any further.
"""

from __future__ import annotations

import re

from primarysource.errors import LibError
from primarysource.refs import RefGrammar

MAX_NAME = 120
_WORDS = r"draft-[a-z0-9]+(?:-[a-z0-9]+)*"
_NAME = re.compile(_WORDS)
_REVISION = re.compile(r"[0-9]{2}")
_DOC = re.compile(r"(?P<name>draft-[a-z0-9]+(?:-[a-z0-9]+)*?)(?:-(?P<rev>[0-9]{2}))?")

DOC_PATTERN = r"draft-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
"""For the ref grammar: the name, with or without its revision. Case is folded by `split_doc`."""

SECTION_PATTERN = r"[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*"
"""A section id: `5.1`, `A.2` (an appendix), or a title slug for an unnumbered section (`abstract`)."""

GRAMMAR = RefGrammar(DOC_PATTERN, SECTION_PATTERN)

_HINT = "a draft is named draft-<words>, optionally followed by -NN, e.g. draft-ietf-sidrops-8210bis-17"


def parse_name(text: str) -> str:
    """A draft name without a revision, or a LibError. Case is folded; nothing else is repaired."""
    name = text.strip().lower()
    if len(name) > MAX_NAME or not _NAME.fullmatch(name):
        raise LibError(f"not a draft name: {text[:60]!r}", _HINT)
    return name


def valid_revision(text: str) -> str:
    """A two-digit revision, or a LibError."""
    if not _REVISION.fullmatch(text):
        raise LibError(f"not a revision: {text[:20]!r}", "a revision is two digits, 00 to 99")
    return text


def split_doc(text: str) -> tuple[str, str | None]:
    """`draft-x-y-17` -> (`draft-x-y`, `17`); `draft-x-y` -> (`draft-x-y`, None)."""
    doc = text.strip().lower()
    if len(doc) > MAX_NAME + 3:
        raise LibError(f"not a draft name: {text[:60]!r}", _HINT)
    match = _DOC.fullmatch(doc)
    if match is None:
        raise LibError(f"not a draft name: {text[:60]!r}", _HINT)
    return parse_name(match["name"]), match["rev"]


def with_revision(name: str, rev: str) -> str:
    """`draft-x-y` and `17` -> `draft-x-y-17`."""
    return f"{parse_name(name)}-{valid_revision(rev)}"
