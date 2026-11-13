"""The `gitdocs` collection: the `Documentation/` tree of git/git, read as AsciiDoc.

Source, placement and pin (read from the repository on 2026-11-13, see `docs/gitdocs.md`):

- the tree is `Documentation/` at the commit of the tag `v2.56.1`. It is fetched as a gitiles subtree archive from
  kernel.googlesource.com (a few MB), because the whole-repository tarball from GitHub is two orders larger for
  the same files; the GitHub tarball is the second source and must give the same manifest digest;
- the licence is GPL-2.0-only, from `COPYING` at the repository root (it says "the only valid version of the GPL
  as far as this project is concerned is _this_ particular version", i.e. v2). `COPYING` is not inside the
  `Documentation/` subtree, so it is named as evidence rather than read by the importer;
- placement is **layer**: the text may be baked into an image. GPL-2.0 asks that the licence and the source stay
  available to the recipient, which a layer that carries `gitdocs status` and the pin satisfies.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

from primarysource.errors import LibError
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.model import Doc
from primarysource.pkgdocs.readers.asciidoc import read_asciidoc
from primarysource.pkgdocs.runtime import Build, Licence, Pin, Spec, TreeSpec, matching

COMMIT = "03b41523c576f26ad34085378717a0c1b287470f"

PIN = Pin(
    commit=COMMIT,
    label="v2.56.1",
    date="2026-10-23",
    files_sha256="3a6d1e943dd8fe4aff27ffb5c4c0949a5a0f170b35a1413aecf4ae62e208a9bb",
    sources=(
        Source(
            f"https://kernel.googlesource.com/pub/scm/git/git/+archive/{COMMIT}/Documentation.tar.gz",
            strip=0,
        ),
        Source(
            f"https://codeload.github.com/git/git/tar.gz/{COMMIT}",
            strip=1,
            hosts=("codeload.github.com",),
            subdir="Documentation",
        ),
    ),
)

LICENCE = Licence(
    spdx="GPL-2.0-only",
    redistribute="layer",
    attribution="Copyright the Git contributors",
    evidence="COPYING at git/git " + COMMIT[:12],
)

_MAN_TITLE = re.compile(r"[\w.+-]+\(\d\)")


def _manpage_title(doc: Doc) -> Doc:
    """`git-tag(1)` plus its NAME line's description: `git-tag(1) - Create, list, delete or verify tags`."""
    if not _MAN_TITLE.fullmatch(doc.title):
        return doc
    for section in doc.sections:
        if section.anchor == "name" and section.units:
            _, sep, description = section.units[0].partition(" - ")
            if sep:
                return Doc(
                    doc.id,
                    f"{doc.title} - {' '.join(description.split())}",
                    doc.unit,
                    doc.sections,
                    doc.meta,
                    doc.warnings,
                )
    return doc


def build(files: Mapping[str, bytes], pin: Pin) -> Build:
    docs: list[Doc] = []
    skipped: Counter[str] = Counter()
    for path in sorted(files):
        try:
            doc = read_asciidoc(files[path], path.removesuffix(".adoc"))
        except LibError:
            skipped["not UTF-8 text"] += 1
            continue
        docs.append(_manpage_title(doc).with_meta(path=f"Documentation/{path}"))
    return Build(tuple(docs), {}, skipped)


SPEC = Spec(
    name="gitdocs",
    title="git Documentation",
    licence=LICENCE,
    trees=(
        TreeSpec(
            name="documentation",
            title="Documentation/ of git/git (AsciiDoc)",
            pins=(PIN,),
            include=matching(r"[A-Za-z0-9][A-Za-z0-9._+/-]*\.adoc"),
            build=build,
        ),
    ),
    instructions=(
        "git's own Documentation/ (manual pages, gitformat-*, gitprotocol-*, technical/ notes, release notes) from "
        "the user's imported copy at a pinned release. Loop: gitdocs_search('<words>') or gitdocs_docs('gitformat') "
        "-> gitdocs_outline('<doc>') -> gitdocs_read('<ref>'). A document id is its path without .adoc "
        "(gitformat-pack, technical/commit-graph, RelNotes/2.50.0). A section is an id (4.2), an anchor or a heading "
        "or a unique part of one. include:: lines are not expanded; they read '[include] <path>' and the included "
        "file is its own document. If nothing is imported the error says how."
    ),
    example_refs=(
        "gitdocs:gitformat-pack§pack-*.idx files have the following format",
        "gitdocs:gitformat-pack@03b4152§5.4¶2",
        "gitdocs:technical/commit-graph§Chunk Format",
    ),
)
