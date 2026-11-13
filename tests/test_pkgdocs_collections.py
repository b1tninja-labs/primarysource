"""The six collections: catalogue sanity, builds over invented files, and imports through injected transports."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from pkgdocs_fixture import make_tar, no_wait, opener_for

from primarysource.debpolicy import catalogue as deb
from primarysource.errors import LibError
from primarysource.gitdocs import catalogue as git
from primarysource.kconfig import catalogue as kconfig
from primarysource.pep import catalogue as pep
from primarysource.pkgdocs import fetch
from primarysource.pkgdocs.runtime import Library, Pin, Spec, TreeSpec
from primarysource.pms import catalogue as pms
from primarysource.rpmdocs import catalogue as rpm

SPECS = [git.SPEC, deb.SPEC, rpm.SPEC, pms.SPEC, pep.SPEC, kconfig.SPEC]
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_every_pin_is_a_full_commit_a_digest_and_an_https_source(spec: Spec) -> None:
    for tree in spec.trees:
        assert tree.pins, tree.name
        for pin in tree.pins:
            assert re.fullmatch(r"[0-9a-f]{40}", pin.commit), (spec.name, pin.label)
            assert pin.files_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", pin.files_sha256)
            assert re.fullmatch(r"20\d\d-\d\d-\d\d", pin.date)
            assert pin.sources and all(s.url.startswith("https://") for s in pin.sources)
            assert all(pin.commit in s.url for s in pin.sources), "a source URL names the pinned commit"
            for source in pin.sources:
                assert set(source.hosts) <= {"codeload.github.com"}


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_every_collection_declares_a_licence_a_placement_and_loadable_refs(spec: Spec, tmp_path: Path) -> None:
    assert spec.licence.spdx and spec.licence.redistribute == "layer" and spec.licence.evidence
    assert spec.prefix == f"{spec.name}_"
    library = Library(spec, tmp_path)
    for example in spec.example_refs:
        ref, _ = library._parse(example)
        assert ref.doc or ref.section, example
    assert "Loop:" in spec.instructions


def test_share_alike_attribution_travels_in_every_citation_of_pms() -> None:
    assert pms.SPEC.licence.spdx == "CC-BY-SA-4.0" and "Bennett" in pms.SPEC.licence.credit


def test_no_file_in_the_collection_packages_or_docs_is_corpus_text() -> None:
    suspicious = {".adoc", ".rst", ".md", ".pod", ".scd", ".tex", ".txt", ".html", ".pdf"}
    names = ("pkgdocs", "gitdocs", "debpolicy", "rpmdocs", "pms", "pep", "kconfig")
    found = [p.name for n in names for p in (ROOT / "primarysource" / n).rglob("*") if p.suffix in suspicious]
    assert found == []
    largest = max(p.stat().st_size for n in names for p in (ROOT / "primarysource" / n).rglob("*.py"))
    assert largest < 40_000, "a collection module that large is carrying data, not code"


GIT_MAN = """git-widget(1)
=============

NAME
----
git-widget - Frobnicate a widget

DESCRIPTION
-----------
Does things. See include::other.adoc[] below.

include::config/widget.adoc[]
"""


def test_gitdocs_titles_a_manual_page_with_its_name_line_and_skips_non_text() -> None:
    build = git.build({"git-widget.adoc": GIT_MAN.encode(), "technical/bad.adoc": b"\xff\xfe"}, git.PIN)
    [doc] = build.docs
    assert doc.id == "git-widget" and doc.title == "git-widget(1) - Frobnicate a widget"
    assert doc.meta["path"] == "Documentation/git-widget.adoc"
    assert dict(build.skipped) == {"not UTF-8 text": 1}
    assert doc.sections[1].units[-1] == "[include] config/widget.adoc"


PEP_9999 = """PEP: 9999
Title: A Fictional Widget Protocol
Author: Nobody <n@example.invalid>,
        Somebody Else
Status: Final
Type: Standards Track
Topic: Packaging
Created: 01-Jan-2020

.. canonical-spec:: :ref:`widgets`

Abstract
========

This PEP describes widgets.

Specification
=============

Widgets MUST frob.

Rationale
---------

Because.

Copyright
=========

This document is placed in the public domain or under the CC0-1.0-Universal license, whichever is more permissive.
"""


def test_pep_header_licence_aliases_and_appendices() -> None:
    files = {
        "pep-9999.rst": PEP_9999.encode(),
        "pep-0003.rst": b"PEP: 3\nTitle: Old\n\nBody\n====\n\ntext without a statement\n",
        "pep-0005.rst": b"PEP: 5\nTitle: Fifth\n\nCopyright\n=========\n\nPlaced into the public domain.\n",
        "pep-0437.rst": b"PEP: 437\nTitle: Open\n\nCopyright\n=========\n\nUnder the `Open Publication License`_.\n",
        "pep-9999/appendix-x.rst": b"Appendix\n========\n\nmore\n",
        "pep-9999.png": b"\x89PNG",
        "pep-0001.rst": b"\xff\xfe",
    }
    build = pep.build(files, pep.PIN)
    docs = {d.id: d for d in build.docs}
    assert sorted(docs) == ["3", "437", "5", "9999", "9999/appendix-x"]
    main = docs["9999"]
    assert main.title == "PEP 9999 - A Fictional Widget Protocol"
    assert main.meta["status"] == "Final" and main.meta["author"].endswith("Somebody Else")
    assert main.meta["path"] == "peps/pep-9999.rst" and main.meta["licence"] == "public-domain-or-cc0"
    assert [s.id for s in main.sections] == ["0", "1", "2", "2.1", "3"]
    assert main.sections[0].units[0].startswith("PEP: 9999\nTitle: A Fictional Widget Protocol")
    assert main.sections[0].units[1].startswith("[canonical-spec]")
    assert {i: docs[i].meta["licence"] for i in ("3", "5", "437")} == {
        "3": "unstated",
        "5": "public-domain",
        "437": "open-publication-license",
    }
    assert build.aliases["pep-0003"] == "3" and build.aliases["0003"] == "3"
    assert dict(build.skipped) == {"not a PEP source": 1, "not UTF-8 text": 1}
    assert pep.licence_counts(list(build.docs))["unstated"] == 1


def test_a_pep_without_a_header_or_without_a_preamble_still_has_its_header_block_first() -> None:
    fields, body = pep.split_header("Not a PEP\n\nbody")
    assert fields == {} and body == "Not a PEP\n\nbody"
    doc = pep.read_pep(b"PEP: 7\nTitle: Seven\n\nOnly\n====\n\nx\n\nAgain\n=====\n\ny\n", "7", "0007")
    assert doc.sections[0].id == "0" and doc.sections[0].units == ("PEP: 7\nTitle: Seven",)


DEB_INDEX = """=====
Index
=====

.. toctree::
   :maxdepth: 4
   :numbered:

   ch-scope
   ch-binary

.. toctree::
   :caption: Appendices
   :numbered:

   ap-misc
"""
DEB_CH = "Chapter title\n=============\n\nlead\n\n.. _s-sub:\n\nSub\n---\n\nsub text\n\nDeeper\n~~~~~~\n\nmore\n"
DEB_COPYRIGHT = """Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/

Files:
 *
Copyright: someone
License: GPL-2+

Files:
 policy/ap-*.rst
 debconf/*
License: BSD-3-clause
"""


def test_debpolicy_numbers_chapters_by_toctree_order_and_reads_the_licence_from_copyright() -> None:
    files = {
        "policy/index.rst": DEB_INDEX.encode(),
        "policy/ch-binary.rst": DEB_CH.encode(),
        "policy/ch-scope.rst": DEB_CH.encode(),
        "policy/ap-misc.rst": DEB_CH.encode(),
        "policy/ch-extra.rst": DEB_CH.encode(),
        "autopkgtest.md": b"# Tests\n\nx\n",
        "policy/conf.py": b"ignored",
        "debian/copyright": DEB_COPYRIGHT.encode(),
    }
    build = deb.build_policy(files, deb.POLICY_PIN)
    docs = {d.id: d for d in build.docs}
    assert sorted(docs) == ["ap-misc", "autopkgtest", "ch-binary", "ch-extra", "ch-scope", "index"]
    assert build.aliases == {"1": "ch-scope", "2": "ch-binary"}
    assert [s.id for s in docs["ch-binary"].sections] == ["2", "2.1", "2.1.1"]
    assert docs["ch-binary"].title == f"Debian Policy {deb.POLICY_PIN.label} chapter 2: Chapter title"
    assert docs["ch-binary"].sections[1].anchor == "s-sub"
    assert [s.id for s in docs["ap-misc"].sections] == ["0", "1", "1.1"], "appendices are numbered locally"
    assert docs["ch-extra"].sections[0].id == "0", "a chapter outside the toctree has no number"
    assert {k: v.meta["licence"] for k, v in docs.items() if k != "index"} == {
        "ap-misc": "BSD-3-clause",
        "autopkgtest": "GPL-2.0-or-later",
        "ch-binary": "GPL-2.0-or-later",
        "ch-extra": "GPL-2.0-or-later",
        "ch-scope": "GPL-2.0-or-later",
    }


def test_debpolicy_says_so_when_the_copyright_file_is_missing() -> None:
    build = deb.build_policy({"policy/ch-scope.rst": DEB_CH.encode()}, deb.POLICY_PIN)
    assert "licences unchecked" in next(iter(build.skipped))
    assert build.docs[0].meta["licence"] == "unchecked"


def test_dep5_last_matching_stanza_wins_and_star_matches_slashes() -> None:
    stanzas = deb._copyright_stanzas(DEB_COPYRIGHT)
    assert deb.licence_of("policy/ch-a.rst", stanzas) == "GPL-2+"
    assert deb.licence_of("policy/ap-b.rst", stanzas) == "BSD-3-clause"
    assert deb.licence_of("debconf/x/y.xml", stanzas) == "BSD-3-clause"
    assert deb.licence_of("anything", []) == ""


MAKEFILE = (
    "man_MANS = \\\n\tdeb-thing.5 \\\n\tdpkg-tool.1 \\\n\t# EOL\n\n"
    "if X\nman_MANS += \\\n\textra.8 \\\n\t# EOL\nendif\n"
)
POD_PAGE = """# header comment
# either version 2 of the License, or (at your option) any later version.

=head1 NAME

deb-thing - Describe a thing

=head1 DESCRIPTION

Text.
"""


def test_dpkg_pages_take_their_section_from_man_mans_and_name_their_licence_header() -> None:
    assert deb.man_sections(MAKEFILE.encode()) == {"deb-thing": "5", "dpkg-tool": "1", "extra": "8"}
    files = {
        "man/Makefile.am": MAKEFILE.encode(),
        "man/deb-thing.pod": POD_PAGE.encode(),
        "man/unlisted.pod": b"=head1 NAME\n\nunlisted - A page\n",
        "man/other.txt": b"x",
    }
    build = deb.build_dpkg(files, deb.DPKG_PIN)
    docs = {d.id: d for d in build.docs}
    assert docs["deb-thing"].title == "deb-thing(5) - Describe a thing"
    assert docs["deb-thing"].meta["licence"] == "GPL-2.0-or-later" and docs["deb-thing"].meta["man_section"] == "5"
    assert docs["unlisted"].title == "unlisted - A page" and docs["unlisted"].meta["licence"] == "see file"
    assert build.aliases == {"deb-thing.5": "deb-thing"}
    assert dict(build.skipped) == {"page not listed in man_MANS: no manual section": 1}


def test_kconfig_records_a_file_spdx_tag_or_the_default() -> None:
    files = {
        "kconfig-language.rst": b".. SPDX-License-Identifier: GPL-2.0-only\n\n===\nKL\n===\n\nIntro\n-----\n\nx",
        "kbuild.rst": b"Kbuild\n======\n\nx\n",
        "bad.rst": b"\xff",
    }
    build = kconfig.build(files, kconfig.PIN)
    docs = {d.id: d for d in build.docs}
    assert docs["kconfig-language"].meta["licence"] == "GPL-2.0-only"
    assert docs["kbuild"].meta["licence"] == "GPL-2.0-only (COPYING, no file tag)"
    assert docs["kconfig-language"].meta["path"] == "Documentation/kbuild/kconfig-language.rst"
    assert dict(build.skipped) == {"not UTF-8 text": 1}


SCD = "RPM-THING(7)\n\n# NAME\n*rpm-thing* - A thing\n\n# DESCRIPTION\nWords.\n"


def test_rpmdocs_ids_man_pages_by_name_and_section_and_titles_them_with_the_name_line() -> None:
    files = {
        "man/rpm-thing.7.scd": SCD.encode(),
        "man/rpm.8.scd": b"RPM(8)\n\n# NAME\n*rpm* - The tool\n",
        "man/index.md": b"# skipped\n",
        "manual/tags.md": b"---\ntitle: rpm.org - Tags\n---\n# Tags\n\nx\n",
    }
    build = rpm.build(files, rpm.PIN)
    docs = {d.id: d for d in build.docs}
    assert sorted(docs) == ["rpm-thing.7", "rpm.8", "tags"]
    assert docs["rpm-thing.7"].title == "rpm-thing(7) - A thing" and docs["tags"].title == "rpm.org - Tags"
    assert build.aliases == {"rpm-thing": "rpm-thing.7", "rpm": "rpm.8"}
    assert dict(build.skipped) == {"not a manual or man page source": 1}


PMS_ROOT = "\\begin{document}\n\\include{intro}\n\\appendix\n\\include{app}\n\\end{document}\n"


def test_pms_is_one_numbered_document_with_chapter_aliases_and_needs_its_root() -> None:
    files = {
        "pms.tex": PMS_ROOT.encode(),
        "intro.tex": b"\\chapter{Intro}\n\\label{ch:intro}\n\n\\section{Aims}\nSee section~\\ref{ch:intro}.\n",
        "app.tex": b"\\chapter{Extra}\n\nx\n",
    }
    build = pms.build(files, pms.PIN)
    [doc] = build.docs
    assert [s.id for s in doc.sections] == ["1", "1.1", "A"]
    assert doc.sections[1].units == ("See section 1.",)
    assert build.aliases["1"] == "pms" and build.aliases["A"] == "pms"
    assert doc.meta["licence"] == "CC-BY-SA-4.0"
    with pytest.raises(LibError, match="pms.tex is not in the archive"):
        pms.build({"intro.tex": b"x"}, pms.PIN)


def rebuilt(spec: Spec, archives: dict[str, dict[str, bytes]]) -> tuple[Spec, dict[str, bytes]]:
    """`spec` with each tree's single pin pointed at a synthetic archive and given its true digest."""
    served: dict[str, bytes] = {}
    trees: list[TreeSpec] = []
    for tree in spec.trees:
        members = archives[tree.name]
        url = f"https://forge.invalid/{tree.name}.tar.gz"
        source = replace(tree.pins[0].sources[0], url=url)
        kept = {n[len(source.subdir) + 1 :] if source.subdir else n: d for n, d in members.items()}
        kept = {n: d for n, d in kept.items() if tree.include(n)}
        pin: Pin = replace(tree.pins[0], files_sha256=fetch.manifest_digest(kept), sources=(source,))
        trees.append(replace(tree, pins=(pin,)))
        served[url] = make_tar(members, prefix="" if source.strip == 0 else "repo-1/")
    return replace(spec, trees=tuple(trees)), served


def test_pep_imports_reads_and_searches_end_to_end(tmp_path: Path) -> None:
    spec, served = rebuilt(pep.SPEC, {"peps": {"peps/pep-9999.rst": PEP_9999.encode(), "README": b"x"}})
    library = Library(spec, tmp_path)
    [report] = library.import_edition(opener=opener_for(served), throttle=no_wait())
    assert report.pinned and report.docs == 1
    text = library.read("pep:9999§Specification")
    assert "Widgets MUST frob." in text and "Rationale" in text
    assert library.read("pep-9999§Rationale").splitlines()[0].endswith("Rationale")
    assert "Status: Final" in library.read("9999§0¶1")
    assert "9999" in library.search("fictional widget protocol")
    cite = library.cite("pep:9999§Specification").splitlines()[0]
    assert "PEP 9999 - A Fictional Widget Protocol" in cite and "peps/pep-9999.rst" in cite


def test_debpolicy_imports_two_trees_and_resolves_policy_numbers_and_man_pages(tmp_path: Path) -> None:
    archives = {
        "policy": {
            "policy/index.rst": DEB_INDEX.encode(),
            "policy/ch-scope.rst": DEB_CH.encode(),
            "policy/ch-binary.rst": DEB_CH.encode(),
            "debian/copyright": DEB_COPYRIGHT.encode(),
        },
        "dpkg": {"man/Makefile.am": MAKEFILE.encode(), "man/deb-thing.pod": POD_PAGE.encode()},
    }
    spec, served = rebuilt(deb.SPEC, archives)
    library = Library(spec, tmp_path)
    reports = library.import_edition(opener=opener_for(served), throttle=no_wait())
    assert [r.tree for r in reports] == ["policy", "dpkg"]
    assert "sub text" in library.read("debpolicy:2.1")
    assert library.read("2.1.1").startswith("### 2.1.1 Deeper")
    assert library.read("ch-binary#s-sub") == library.read("2.1")
    assert "Text." in library.read("deb-thing.5§DESCRIPTION")
    assert library.docs("deb").splitlines()[0] == "deb-thing  deb-thing(5) - Describe a thing"
    found = library.search("sub text deeper")
    assert "ch-binary" in found
    commit = deb.DPKG_PIN.commit[:7]
    assert "Text." in library.read(f"deb-thing@{commit}§DESCRIPTION")
    status = library.status()
    assert "tree policy:" in status and "tree dpkg:" in status
    with pytest.raises(LibError, match="--archive needs --tree"):
        library.import_edition(archive="x.tar.gz")


def test_pms_and_kconfig_and_rpmdocs_import_from_their_own_layouts(tmp_path: Path) -> None:
    spec, served = rebuilt(
        pms.SPEC,
        {
            "pms": {
                "pms.tex": PMS_ROOT.encode(),
                "intro.tex": b"\\chapter{Intro}\n\nx\n",
                "app.tex": b"\\chapter{E}\n",
            }
        },
    )
    library = Library(spec, tmp_path / "pms")
    library.import_edition(opener=opener_for(served), throttle=no_wait())
    assert library.read("pms:1").startswith("# 1 Intro")
    spec, served = rebuilt(
        kconfig.SPEC, {"kbuild": {"kconfig-language.rst": b"=====\nKL\n=====\n\nMenu entries\n------------\n\nx\n"}}
    )
    library = Library(spec, tmp_path / "kconfig")
    library.import_edition(opener=opener_for(served), throttle=no_wait())
    assert "x" in library.read("kconfig-language§Menu entries")
    spec, served = rebuilt(
        rpm.SPEC,
        {
            "docs": {
                "docs/manual/tags.md": b"# Tags\n\n## Tag types\n\nx\n",
                "docs/man/rpm.8.scd": b"RPM(8)\n\n# NAME\n*rpm* - t\n",
            }
        },
    )
    library = Library(spec, tmp_path / "rpm")
    library.import_edition(opener=opener_for(served), throttle=no_wait())
    assert "x" in library.read("tags§Tag types") and "*rpm* - t" in library.read("rpm§NAME")
    spec, served = rebuilt(git.SPEC, {"documentation": {"git-x.adoc": GIT_MAN.encode(), "notes.txt": b"n"}})
    library = Library(spec, tmp_path / "git")
    library.import_edition(opener=opener_for(served), throttle=no_wait())
    assert "Does things." in library.read("git-x§DESCRIPTION")
