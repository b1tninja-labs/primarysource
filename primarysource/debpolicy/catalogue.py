"""The `debpolicy` collection: Debian Policy (reStructuredText) and the dpkg manual pages (POD).

Two pinned trees, so two editions that move independently:

- `policy`: dbnpolicy/policy on salsa.debian.org at the commit of the tag `debian/4.7.4.1`. The documents are
  `policy/*.rst` (chapters `ch-*`, appendices `ap-*`, `upgrading-checklist`, `index`) and `autopkgtest.md`;
- `dpkg`: dpkg-team/dpkg at the tag `1.23.12`. The documents are the 63 `man/*.pod` pages, with their manual
  section taken from `man/Makefile.am` (`man_MANS`). In 1.23.12 the pages are POD, not roff; roff appears only
  after `pod2man`.

Licence (read from the repositories on 2026-11-13, see `docs/debpolicy.md`): the policy tree's `debian/copyright`
(DEP-5) gives `Files: *` as GPL-2+ and names the exceptions (`copyright-format*.xml`, `debconf*`, `fhs-3.0*` and
some diagrams), none of which is imported; the build reads that file and puts the matching `License:` of each
imported document in its meta. Each dpkg page carries its own header, "either version 2 of the License, or (at
your option) any later version", which the POD build reads the same way. Placement is **layer**.

Numbering: a chapter's number is its place in the first `toctree` of `index.rst`, so `ch-controlfields` is
chapter 5 and its subsections are `5.1`, `5.6.1`. `debpolicy:5.6.1` works without a document id for that
reason. Appendices are numbered locally inside their own document (the build does not claim Sphinx's appendix
numbering, which was not checked).
"""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from collections.abc import Mapping

from primarysource.errors import LibError
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import decode
from primarysource.pkgdocs.readers.markdown import read_markdown
from primarysource.pkgdocs.readers.pod import read_pod
from primarysource.pkgdocs.readers.rst import read_rst
from primarysource.pkgdocs.runtime import Build, Licence, Pin, Spec, TreeSpec, matching

POLICY_COMMIT = "aceb1daf7305adc0b336ee2ebbdf0bc0340d3b68"
DPKG_COMMIT = "f78cedcdcbbf25b27f3104b99ac3d2832e19d0cc"

POLICY_PIN = Pin(
    commit=POLICY_COMMIT,
    label="4.7.4.1",
    date="2026-03-31",
    files_sha256="bcf7ce3c75512efe7274fedf88a8c615483e50872c9fd644c678a816f8b3319b",
    sources=(
        Source(
            f"https://salsa.debian.org/dbnpolicy/policy/-/archive/{POLICY_COMMIT}/policy-{POLICY_COMMIT}.tar.gz",
            strip=1,
        ),
    ),
)
DPKG_PIN = Pin(
    commit=DPKG_COMMIT,
    label="1.23.12",
    date="2026-11-13",
    files_sha256="22d4c9ed26c64e136510ae6d7f002b7afb309613223bc88ef025413b8b47e610",
    sources=(
        Source(f"https://salsa.debian.org/dpkg-team/dpkg/-/archive/{DPKG_COMMIT}/dpkg-{DPKG_COMMIT}.tar.gz", strip=1),
        Source(
            f"https://github.com/guillemj/dpkg/archive/{DPKG_COMMIT}.tar.gz",
            strip=1,
            hosts=("codeload.github.com",),
        ),
    ),
)

LICENCE = Licence(
    spdx="GPL-2.0-or-later",
    redistribute="layer",
    attribution="Debian Policy: Ian Jackson, Christian Schwarz and many other Debian contributors; "
    "dpkg: Guillem Jover and others",
    evidence="debian/copyright (`Files: *`, License: GPL-2+) in the policy tree; the header of each dpkg .pod",
)

_GPL2_PLUS = "GPL-2.0-or-later"
_MAN_MANS = re.compile(r"man_MANS\s*\+?=\s*((?:[^\n]*\\\n)*[^\n]*)")
_PAGE = re.compile(r"([\w.+-]+)\.(\d)")


def _copyright_stanzas(text: str) -> list[tuple[list[str], str]]:
    """(file patterns, licence short name) for each DEP-5 `Files:` stanza of a `debian/copyright`."""
    stanzas: list[tuple[list[str], str]] = []
    for block in re.split(r"\n\s*\n", text):
        files: list[str] = []
        licence = ""
        in_files = False
        for line in block.split("\n"):
            if line.startswith("Files:"):
                in_files = True
                files.extend(line[len("Files:") :].split())
            elif in_files and line[:1] in (" ", "\t"):
                files.extend(line.split())
            else:
                in_files = False
                if line.startswith("License:"):
                    licence = line[len("License:") :].strip()
        if files and licence:
            stanzas.append((files, licence))
    return stanzas


def licence_of(path: str, stanzas: list[tuple[list[str], str]]) -> str:
    """The licence DEP-5 gives `path`: the last `Files:` stanza that matches it (`*` also matches `/`)."""
    found = ""
    for patterns, licence in stanzas:
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
            found = licence
    return found


def _chapter_order(index: bytes | None) -> list[str]:
    """Document stems in the first `toctree` of `index.rst`, in order."""
    if index is None:
        return []
    stems: list[str] = []
    in_tree = False
    for line in decode(index, "policy/index.rst").split("\n"):
        if line.startswith(".. toctree::"):
            if stems:
                break
            in_tree = True
        elif in_tree and line.strip() and line.startswith(("   ", "\t")) and not line.strip().startswith(":"):
            stems.append(line.strip())
        elif in_tree and line.strip() and not line.startswith((" ", "\t")):
            break
    return stems


def build_policy(files: Mapping[str, bytes], pin: Pin) -> Build:
    stanzas = (
        _copyright_stanzas(decode(files["debian/copyright"], "debian/copyright"))
        if "debian/copyright" in files
        else []
    )
    order = _chapter_order(files.get("policy/index.rst"))
    docs: list[Doc] = []
    aliases: dict[str, str] = {}
    skipped: Counter[str] = Counter()
    if not stanzas:
        skipped["debian/copyright not found or has no Files stanza: licences unchecked"] += 1
    for path in sorted(files):
        if path == "debian/copyright":
            continue
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        try:
            if path.startswith("policy/") and path.endswith(".rst"):
                number = str(order.index(stem) + 1) if stem.startswith("ch-") and stem in order else ""
                doc = read_rst(files[path], stem, base=number)
                if number:
                    aliases[number] = stem
                    doc = Doc(
                        doc.id,
                        f"Debian Policy {pin.label} chapter {number}: {doc.title}",
                        doc.unit,
                        doc.sections,
                        doc.meta,
                        doc.warnings,
                    )
                elif stem != "index":
                    doc = Doc(
                        doc.id,
                        f"Debian Policy {pin.label}: {doc.title}",
                        doc.unit,
                        doc.sections,
                        doc.meta,
                        doc.warnings,
                    )
            elif path.endswith(".md"):
                doc = read_markdown(files[path], stem)
            else:
                skipped["not a policy document"] += 1
                continue
        except LibError:
            skipped["not UTF-8 text"] += 1
            continue
        found = licence_of(path, stanzas)
        docs.append(doc.with_meta(path=path, licence=_GPL2_PLUS if found == "GPL-2+" else (found or "unchecked")))
    return Build(tuple(docs), aliases, skipped)


def man_sections(makefile: bytes | None) -> dict[str, str]:
    """`{page: section}` from the `man_MANS` lists of `man/Makefile.am` (`deb-control.5` -> `deb-control: 5`)."""
    if makefile is None:
        return {}
    sections: dict[str, str] = {}
    for match in _MAN_MANS.finditer(decode(makefile, "man/Makefile.am")):
        for token in match.group(1).replace("\\\n", " ").split():
            found = _PAGE.fullmatch(token)
            if found:
                sections[found.group(1)] = found.group(2)
    return sections


def build_dpkg(files: Mapping[str, bytes], pin: Pin) -> Build:
    sections = man_sections(files.get("man/Makefile.am"))
    docs: list[Doc] = []
    aliases: dict[str, str] = {}
    skipped: Counter[str] = Counter()
    for path in sorted(files):
        if not (path.startswith("man/") and path.endswith(".pod")):
            continue
        page = path[len("man/") : -len(".pod")]
        try:
            doc = read_pod(files[path], page)
        except LibError:
            skipped["not UTF-8 text"] += 1
            continue
        number = sections.get(page, "")
        if not number:
            skipped["page not listed in man_MANS: no manual section"] += 1
        _, _, description = doc.title.partition(" - ")
        title = f"{page}({number})" + (f" - {description}" if description else "") if number else doc.title
        text = decode(files[path], path)
        licence = (
            _GPL2_PLUS
            if "either version 2 of the License, or" in text and "any later version" in text
            else "see file"
        )
        doc = Doc(doc.id, title, doc.unit, doc.sections, doc.meta, doc.warnings)
        docs.append(doc.with_meta(path=path, licence=licence, man_section=number))
        if number:
            aliases[f"{page}.{number}"] = page
    return Build(tuple(docs), aliases, skipped)


SPEC = Spec(
    name="debpolicy",
    title="Debian Policy and the dpkg manual pages",
    licence=LICENCE,
    trees=(
        TreeSpec(
            name="policy",
            title="Debian Policy Manual (policy/*.rst, autopkgtest.md)",
            pins=(POLICY_PIN,),
            include=matching(r"policy/[a-z0-9-]+\.rst|autopkgtest\.md|debian/copyright"),
            build=build_policy,
        ),
        TreeSpec(
            name="dpkg",
            title="dpkg manual pages (man/*.pod)",
            pins=(DPKG_PIN,),
            include=matching(r"man/[A-Za-z0-9.+-]+\.pod|man/Makefile\.am"),
            build=build_dpkg,
        ),
    ),
    instructions=(
        "Debian Policy (chapters 1-12 and the appendices) and the dpkg manual pages (deb(5), deb-control(5), "
        "dpkg-deb(1), ...) from the user's imported copies at pinned releases. Loop: debpolicy_search('<words>') -> "
        "debpolicy_outline('<doc>') -> debpolicy_read('<ref>'). Policy section numbers work as refs: '5.6.1' is "
        "the Source field of chapter 5 (ch-controlfields); chapters are the documents ch-* and appendices ap-*. "
        "A dpkg page's document id is its name ('deb-control'); 'deb-control.5' works too. A section is an id, an "
        "anchor (Policy's s-f-Source), a heading or a unique part of one. If nothing is imported the error says "
        "how."
    ),
    example_refs=(
        "debpolicy:5.6.1",
        "debpolicy:ch-controlfields§s-f-Source",
        "debpolicy:deb-control§DESCRIPTION",
        "debpolicy:5.6.1@aceb1daf¶2",
    ),
)
