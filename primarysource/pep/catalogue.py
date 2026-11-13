"""The `pep` collection: the Python Enhancement Proposals in python/peps, read as reStructuredText.

Source, placement and pin (read from the repository on 2026-11-13, see `docs/pep.md`):

- the tree is `peps/` of python/peps at one `main` commit, fetched as a GitHub tarball. Each PEP is
  `peps/pep-NNNN.rst`; the few with appendices also have `peps/pep-NNNN/*.rst`;
- the licence is per document, not per repository (the repository has no LICENSE file at the root). Each PEP's own
  "Copyright" section is the statement, and the build classifies it into the document's `licence` meta. Measured
  at this commit over the 747 PEP files: 246 say "placed in the public domain or under the CC0-1.0-Universal
  license, whichever is more permissive" (`public-domain-or-cc0`), 467 say "public domain" in other words
  (`public-domain`), 6 name the Open Publication License (`open-publication-license`) and 28 carry no statement
  (`unstated`, the oldest); the 14 appendix files are `see-parent-pep`. The import prints none of this, `status`
  does not either: read the meta, or `licence_counts`, when deciding placement per document;
- placement is **layer** for the collection, with that caveat recorded: the statement is read from the text, the
  repository carries no machine-readable licence for it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

from primarysource.errors import LibError
from primarysource.model import Unit
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.model import Doc, Sec
from primarysource.pkgdocs.readers._common import decode
from primarysource.pkgdocs.readers.rst import read_rst
from primarysource.pkgdocs.runtime import Build, Licence, Pin, Spec, TreeSpec, matching

COMMIT = "155e5bee7d985ef30555b496eb994d24a591f70b"

PIN = Pin(
    commit=COMMIT,
    label="main 2026-11-12",
    date="2026-11-12",
    files_sha256="6d4a01026a0a2c4b81ecb18d6e23939cc6ba59f6ffc41b7f3d614238951343e8",
    sources=(
        Source(f"https://codeload.github.com/python/peps/tar.gz/{COMMIT}", strip=1, subdir="peps"),
        Source(
            f"https://github.com/python/peps/archive/{COMMIT}.tar.gz",
            strip=1,
            hosts=("codeload.github.com",),
            subdir="peps",
        ),
    ),
)

LICENCE = Licence(
    spdx="CC0-1.0 OR LicenseRef-public-domain",
    redistribute="layer",
    attribution="each PEP is by its authors; the licence is the one in its own Copyright section",
    evidence="the Copyright section of each pep-NNNN.rst; per-document result in meta `licence`",
)

_FILE = re.compile(r"pep-(\d{4})\.rst")
_APPENDIX = re.compile(r"pep-(\d{4})/([A-Za-z0-9._-]+)\.rst")
_KEY = re.compile(r"([A-Za-z][A-Za-z-]*):[ \t]*(.*)")


def _licence_of(text: str) -> str:
    """Which licence statement a PEP carries, from its text: `public-domain-or-cc0` (the standard one),
    `public-domain`, `open-publication-license` or `unstated`."""
    low = text.lower()
    if "placed in the public domain or under the cc0-1.0-universal" in low or "whichever is more permissive" in low:
        return "public-domain-or-cc0"
    if "open publication license" in low:
        return "open-publication-license"
    if "public domain" in low:
        return "public-domain"
    return "unstated"


def split_header(text: str) -> tuple[dict[str, str], str]:
    """The RFC 822 style header at the top of a PEP and the body after it. A text whose first line is not
    `PEP: <n>` has no header: the whole text is the body."""
    head, sep, body = text.partition("\n\n")
    if not head.startswith("PEP:"):
        return {}, text
    fields: dict[str, str] = {}
    last = ""
    for line in head.split("\n"):
        if line[:1] in (" ", "\t") and last:
            fields[last] += " " + line.strip()
            continue
        found = _KEY.fullmatch(line)
        if found:
            last = found.group(1).lower().replace("-", "_")
            fields[last] = found.group(2).strip()
    return fields, body if sep else ""


def read_pep(data: bytes, doc_id: str, number: str) -> Doc:
    """A PEP: its header as block 1 of section `0`, its meta from the header, its body as reStructuredText."""
    text = decode(data, f"PEP {number}")
    fields, body = split_header(text)
    title = f"PEP {int(number)} - {fields['title']}" if fields.get("title") else f"PEP {int(number)}"
    doc = read_rst(body.encode("utf-8"), doc_id, title)
    header = text[: len(text) - len(body)].rstrip() if fields else ""
    sections = doc.sections
    if header:
        if sections and sections[0].id == "0":
            first = sections[0]
            sections = (Sec("0", first.title, first.depth, first.anchor, (header, *first.units)), *sections[1:])
        else:
            sections = (Sec("0", title, 1, "header", (header,)), *sections)
    meta = {k: v for k, v in fields.items() if k in _META_KEYS}
    meta["licence"] = _licence_of(body)
    return Doc(doc_id, title, Unit.BLOCK, sections, meta, doc.warnings)


_META_KEYS = frozenset(
    {
        "title",
        "author",
        "status",
        "type",
        "topic",
        "created",
        "python_version",
        "replaces",
        "superseded_by",
        "requires",
        "resolution",
        "discussions_to",
        "post_history",
        "pep",
    }
)


def build(files: Mapping[str, bytes], pin: Pin) -> Build:
    docs: list[Doc] = []
    aliases: dict[str, str] = {}
    skipped: Counter[str] = Counter()
    for path in sorted(files):
        main = _FILE.fullmatch(path)
        appendix = _APPENDIX.fullmatch(path)
        try:
            if main:
                number = main.group(1)
                doc_id = str(int(number))
                doc = read_pep(files[path], doc_id, number)
                aliases[f"pep-{number}"] = doc_id
                aliases[number] = doc_id
            elif appendix:
                number = appendix.group(1)
                doc_id = f"{int(number)}/{appendix.group(2)}"
                doc = read_rst(files[path], doc_id, f"PEP {int(number)} appendix {appendix.group(2)}").with_meta(
                    licence="see-parent-pep"
                )
            else:
                skipped["not a PEP source"] += 1
                continue
        except LibError:
            skipped["not UTF-8 text"] += 1
            continue
        docs.append(doc.with_meta(path=f"peps/{path}"))
    return Build(tuple(docs), aliases, skipped)


def licence_counts(docs: Mapping[str, Doc] | list[Doc]) -> Counter[str]:
    """How many documents carry each licence statement (for the import report and the tests)."""
    values = docs.values() if isinstance(docs, Mapping) else docs
    return Counter(d.meta.get("licence", "unstated") for d in values)


SPEC = Spec(
    name="pep",
    title="Python Enhancement Proposals",
    licence=LICENCE,
    trees=(
        TreeSpec(
            name="peps",
            title="peps/ of python/peps (reStructuredText)",
            pins=(PIN,),
            include=matching(r"pep-\d{4}\.rst|pep-\d{4}/[A-Za-z0-9._-]+\.rst"),
            build=build,
        ),
    ),
    instructions=(
        "Python Enhancement Proposals (PEP 440 versions, 427/491 wheels, 517/621 builds and metadata, ...) from "
        "the user's imported copy of python/peps at a pinned commit. Loop: pep_search('<words>') -> "
        "pep_outline('440') -> pep_read('<ref>'). A document id is the PEP number without leading zeros ('440'); "
        "'pep-0440' and '0440' work too, and '440/appendix-x' names an appendix. Section 0 holds the header "
        "(status, authors, dates). A section is an id (3.1), an anchor (version-scheme), a heading or a unique "
        "part of one. Each document's licence statement is in its meta and shown by pep_status counts."
    ),
    example_refs=("pep:440§Version scheme", "pep:440@155e5be§3.1¶2", "pep:517§Build backend interface"),
)
