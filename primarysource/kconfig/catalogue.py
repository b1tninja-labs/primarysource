"""The `kconfig` collection: the kernel's Kconfig and Kbuild documents, read as reStructuredText.

Source, placement and pin (read from the repositories on 2026-11-13, see `docs/kconfig.md`):

- the tree is `Documentation/kbuild/` of torvalds/linux at the commit of the tag `v7.3`, fetched as a gitiles
  subtree archive from kernel.googlesource.com (57 KB; the whole-repository tarball is two orders larger). The
  documents are the twelve `.rst` files there: `kconfig-language` (the language), `kconfig-macro-language`,
  `kconfig` (the configuration targets), `kbuild`, `makefiles`, `modules`, and the rest;
- the licence is GPL-2.0-only: the kernel's `COPYING` at the root says "GPL-2.0 WITH Linux-syscall-note" and
  names the syscall note's scope as the user-space API headers, and `Documentation/process/license-rules.rst`
  gives the kernel as "GPL version 2 only". Three of the twelve files carry an `SPDX-License-Identifier` line;
  the build records it as the document's `licence` and records the rest as `GPL-2.0-only (COPYING, no file tag)`;
- placement is **layer**.

pkgtrust R165 and kconfigpy read `kconfig-language` for the grammar of a Kconfig file; refs into it are
`kconfig:kconfig-language§Menu entries` and, once pinned, `kconfig:kconfig-language@c03c1a14§Menu entries`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

from primarysource.errors import LibError
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers._common import decode
from primarysource.pkgdocs.readers.rst import read_rst
from primarysource.pkgdocs.runtime import Build, Licence, Pin, Spec, TreeSpec, matching

COMMIT = "c03c1a14507dfaf8b856c2608f9ac216021fc222"

PIN = Pin(
    commit=COMMIT,
    label="v7.3",
    date="2026-10-18",
    files_sha256="36d3fe2bf74fee4efef91f7a16a56297966652812e314f8122eb4e5d0cd13ecd",
    sources=(
        Source(
            f"https://kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+archive/{COMMIT}/Documentation/kbuild.tar.gz",
            strip=0,
        ),
    ),
)

LICENCE = Licence(
    spdx="GPL-2.0-only",
    redistribute="layer",
    attribution="Linux kernel developers; GPL-2.0-only",
    evidence="COPYING and Documentation/process/license-rules.rst at torvalds/linux " + COMMIT[:12],
)

_SPDX = re.compile(r"SPDX-License-Identifier:\s*([^\n]+)")


def build(files: Mapping[str, bytes], pin: Pin) -> Build:
    docs: list[Doc] = []
    skipped: Counter[str] = Counter()
    for path in sorted(files):
        stem = path[: -len(".rst")]
        try:
            doc = read_rst(files[path], stem)
            tag = _SPDX.search(decode(files[path], path))
        except LibError:
            skipped["not UTF-8 text"] += 1
            continue
        licence = tag.group(1).strip() if tag else "GPL-2.0-only (COPYING, no file tag)"
        docs.append(doc.with_meta(path=f"Documentation/kbuild/{path}", licence=licence))
    return Build(tuple(docs), {}, skipped)


SPEC = Spec(
    name="kconfig",
    title="Linux Kconfig and Kbuild documentation",
    licence=LICENCE,
    trees=(
        TreeSpec(
            name="kbuild",
            title="Documentation/kbuild/ of torvalds/linux (reStructuredText)",
            pins=(PIN,),
            include=matching(r"[a-z][a-z0-9_.-]*\.rst"),
            build=build,
        ),
    ),
    instructions=(
        "The kernel's Kconfig language reference (kconfig-language), the macro language (kconfig-macro-language), "
        "the configuration targets (kconfig) and the Kbuild documents (kbuild, makefiles, modules, ...) from the "
        "user's imported copy at a pinned release. Loop: kconfig_search('<words>') -> "
        "kconfig_outline('kconfig-language') -> kconfig_read('<ref>'). A document id is its file name without "
        ".rst. A section is an id (2.1), an anchor (menu-entries), a heading or a unique part of one."
    ),
    example_refs=(
        "kconfig:kconfig-language§Menu entries",
        "kconfig:kconfig-language§Menu attributes¶3",
        "kconfig:kconfig-macro-language§Built-in functions",
    ),
)
