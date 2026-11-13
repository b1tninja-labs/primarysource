"""The `rpmdocs` collection: rpm's manual (Markdown) and manual pages (scdoc) from rpm-software-management/rpm.

Source, placement and pin (read from the repository on 2026-11-13, see `docs/rpmdocs.md`):

- the tree is `docs/` at the commit of the tag `rpm-6.1.0-release`: `docs/manual/*.md` (the format documents
  `format_v4`, `format_v6`, `tags`, `spec`, `macros`, `dependencies`, ...) and `docs/man/*.scd` (rpm(8),
  rpm-macros(7), rpm-queryformat(7), ...), fetched as a GitHub tarball (1.2 MB);
- the licence is GPL-2.0-or-later: `COPYING` at the repository root says "In SPDX terms, the entire code base is
  licensed GPL-2.0-or-later", with LGPL-2.0-or-later as an alternative for `lib/` and `rpmio/` only, which are
  not the documentation. The files under `docs/` carry no licence of their own;
- placement is **layer**.

Ids: a manual page is `<name>.<section>` (`rpm-macros.7`, `rpm.8`; `rpm-macros` alone also works), a manual
document is its file name without `.md` (`format_v6`, `tags`).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

from primarysource.errors import LibError
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers.markdown import read_markdown
from primarysource.pkgdocs.readers.scdoc import read_scdoc
from primarysource.pkgdocs.runtime import Build, Licence, Pin, Spec, TreeSpec, matching

COMMIT = "f832c7e69945248dd5bcfcacfd10c176ee300fa2"

PIN = Pin(
    commit=COMMIT,
    label="rpm-6.1.0-release",
    date="2026-08-20",
    files_sha256="610c31cafa342d40c7dd3e507749c1fc90fa32c3550d6b8a3e440f45b4a037b7",
    sources=(
        Source(f"https://codeload.github.com/rpm-software-management/rpm/tar.gz/{COMMIT}", strip=1, subdir="docs"),
        Source(
            f"https://github.com/rpm-software-management/rpm/archive/{COMMIT}.tar.gz",
            strip=1,
            hosts=("codeload.github.com",),
            subdir="docs",
        ),
    ),
)

LICENCE = Licence(
    spdx="GPL-2.0-or-later",
    redistribute="layer",
    attribution="RPM Package Manager contributors",
    evidence="COPYING at rpm-software-management/rpm " + COMMIT[:12] + ' ("In SPDX terms ... GPL-2.0-or-later")',
)

_MAN = re.compile(r"man/([a-z0-9._+-]+\.\d)\.scd")
_MANUAL = re.compile(r"manual/([A-Za-z0-9_.+-]+)\.md")


def build(files: Mapping[str, bytes], pin: Pin) -> Build:
    docs: list[Doc] = []
    aliases: dict[str, str] = {}
    skipped: Counter[str] = Counter()
    for path in sorted(files):
        man = _MAN.fullmatch(path)
        manual = _MANUAL.fullmatch(path)
        try:
            if man:
                page = man.group(1)
                doc = read_scdoc(files[path], page)
                aliases[page.rsplit(".", 1)[0]] = page
                name, section = page.rsplit(".", 1)
                body_title = _name_line(doc)
                title = f"{name}({section})" + (f" - {body_title}" if body_title else "")
                doc = Doc(doc.id, title, doc.unit, doc.sections, doc.meta, doc.warnings)
            elif manual:
                doc = read_markdown(files[path], manual.group(1))
            else:
                skipped["not a manual or man page source"] += 1
                continue
        except LibError:
            skipped["not UTF-8 text"] += 1
            continue
        docs.append(doc.with_meta(path=f"docs/{path}", licence="GPL-2.0-or-later (COPYING, no file tag)"))
    return Build(tuple(docs), aliases, skipped)


def _name_line(doc: Doc) -> str:
    """The description in the NAME section's `*name* - description` line."""
    for section in doc.sections:
        if section.anchor == "name" and section.units:
            _, sep, description = section.units[0].partition(" - ")
            return " ".join(description.split()) if sep else ""
    return ""


SPEC = Spec(
    name="rpmdocs",
    title="RPM documentation",
    licence=LICENCE,
    trees=(
        TreeSpec(
            name="docs",
            title="docs/ of rpm-software-management/rpm (Markdown, scdoc)",
            pins=(PIN,),
            include=matching(r"manual/[A-Za-z0-9_.+-]+\.md|man/[a-z0-9._+-]+\.\d\.scd"),
            build=build,
        ),
    ),
    instructions=(
        "rpm's manual (file formats format_v4/format_v6, tags, spec, macros, dependencies, ...) and manual pages "
        "(rpm.8, rpm-macros.7, rpm-queryformat.7, ...) from the user's imported copy at a pinned release. Loop: "
        "rpmdocs_search('<words>') -> rpmdocs_outline('format_v6') -> rpmdocs_read('<ref>'). A manual document's id "
        "is its file name without .md; a man page's id is name.section ('rpm-macros.7', or just 'rpm-macros'). A "
        "section is an id, an anchor, a heading or a unique part of one."
    ),
    example_refs=("rpmdocs:format_v6§Header", "rpmdocs:tags§Tag types", "rpmdocs:rpm-macros.7§DESCRIPTION"),
)
