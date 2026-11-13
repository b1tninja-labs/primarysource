"""The `pms` collection: the Gentoo Package Manager Specification, read from its LaTeX source.

Source, placement and pin (read from the repository on 2026-11-13, see `docs/pms.md`):

- the tree is the root of gentoo/pms at the commit of the tag `eapi-9-approved-2026-06-14` (the approved EAPI 9
  text), fetched as a GitHub tarball (77 KB). `pms.tex` includes the chapters in order; the build reads them from
  the archive's own files, never from disk, into one document, `pms`, numbered as the typeset specification is
  (chapters 1, 2, ..., then A, B, ... after `\\appendix`);
- the licence is **CC-BY-SA-4.0**, from the title page of `pms.tex`: "released under the Creative Commons
  Attribution-ShareAlike 4.0 International licence". (Group F's notes said 3.0, read on the EAPI 3 page; the
  current source says 4.0, and that is what is recorded.) Placement is **layer, with attribution**: every
  citation carries the credit, and the licence line travels with the layer;
- GLEPs, the other half of the original brief, are not here: gitweb.gentoo.org answered HTTP 502 to the
  snapshot request on 2026-11-13 and the project has no GitHub mirror (`gentoo/glep` and `projg2/glep` are not
  found). See ROADMAP row `col.gentoo_glep`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from primarysource.errors import LibError
from primarysource.pkgdocs.fetch import Source
from primarysource.pkgdocs.readers.latex import read_latex
from primarysource.pkgdocs.runtime import Build, Licence, Pin, Spec, TreeSpec, matching

COMMIT = "2cee9c6bd86851738e8ba1874ac622cfcec70969"

PIN = Pin(
    commit=COMMIT,
    label="eapi-9-approved-2026-06-14",
    date="2026-06-14",
    files_sha256="c302537c3d04c28a69b3e4fae19247f168913a29beff587e2e26d6af08d62502",
    sources=(
        Source(f"https://codeload.github.com/gentoo/pms/tar.gz/{COMMIT}", strip=1),
        Source(f"https://github.com/gentoo/pms/archive/{COMMIT}.tar.gz", strip=1, hosts=("codeload.github.com",)),
    ),
)

LICENCE = Licence(
    spdx="CC-BY-SA-4.0",
    redistribute="layer",
    attribution="(c) 2007-2026 Stephen Bennett, Ciaran McCreesh and others; contributions are owned by their authors",
    evidence="the title page of pms.tex in gentoo/pms " + COMMIT[:12],
    credit="CC BY-SA 4.0, Stephen Bennett, Ciaran McCreesh and others",
)

TITLE = "Package Manager Specification"


def build(files: Mapping[str, bytes], pin: Pin) -> Build:
    skipped: Counter[str] = Counter()
    if "pms.tex" not in files:
        raise LibError("pms.tex is not in the archive", "the repository layout changed; report the collection")
    try:
        doc = read_latex(files, "pms.tex", "pms", f"{TITLE} ({pin.label})")
    except LibError:
        skipped["not UTF-8 text"] += 1
        raise
    aliases = {s.id.split(".")[0]: "pms" for s in doc.sections if s.id != "0"}
    aliases["pms-" + pin.label] = "pms"
    return Build((doc.with_meta(path="pms.tex", licence="CC-BY-SA-4.0"),), aliases, skipped)


SPEC = Spec(
    name="pms",
    title="Gentoo Package Manager Specification",
    licence=LICENCE,
    trees=(
        TreeSpec(
            name="pms",
            title="gentoo/pms (LaTeX)",
            pins=(PIN,),
            include=matching(r"[A-Za-z0-9._-]+\.tex"),
            build=build,
        ),
    ),
    instructions=(
        "The Gentoo Package Manager Specification (PMS), one document, 'pms', numbered as the typeset text is: "
        "chapters 1-14, then appendices A, B, ... Loop: pms_search('<words>') -> pms_outline('pms') -> "
        "pms_read('<ref>'). Section numbers work as refs without a document: 'pms:8.2.4'. A section is an id, "
        "an anchor (the LaTeX label, e.g. ch:ebuild-vars), a heading or a unique part of one. Text is reduced "
        "from LaTeX: \\ref numbers are resolved, markup is dropped, and the warning: line lists the commands "
        "that were dropped. Every citation carries the CC BY-SA 4.0 credit."
    ),
    example_refs=("pms:8.2.4", "pms:pms§Ebuild-defined variables", "pms:pms§ch:ebuild-vars¶2"),
)
