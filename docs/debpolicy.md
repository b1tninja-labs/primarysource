# debpolicy: Debian Policy and the dpkg manual pages

`debpolicy` serves two pinned trees as one collection: the Debian Policy Manual and the dpkg manual pages
(`deb(5)`, `deb-control(5)`, `dpkg-deb(1)`, `deb-version(7)`, ...). It is the primary text for `pkgformats` and
`pkgtrust`.

Install: `pip install "primarysource[debpolicy,mcp]"`. Import: `primarysource debpolicy import` (two requests, 1 MB
and 8.6 MB). Serve: `primarysource mcp --collection debpolicy`. Tools: `debpolicy_read`, `debpolicy_outline`,
`debpolicy_search`, `debpolicy_cite`, `debpolicy_docs`, `debpolicy_status`.

## 1. Source, pin and licence

| | Tree `policy` | Tree `dpkg` |
|---|---|---|
| Repository | dbnpolicy/policy on salsa.debian.org | dpkg-team/dpkg on salsa.debian.org |
| Edition | tag `debian/4.7.4.1`, commit `aceb1daf7305adc0b336ee2ebbdf0bc0340d3b68` (2026-03-31) | tag `1.23.12`, commit `f78cedcdcbbf25b27f3104b99ac3d2832e19d0cc` |
| Fetched from | `salsa.debian.org/dbnpolicy/policy/-/archive/<commit>/policy-<commit>.tar.gz` (1,004,377 bytes) | `salsa.debian.org/dpkg-team/dpkg/-/archive/<commit>/...tar.gz` (8,644,399 bytes); mirror `github.com/guillemj/dpkg/archive/<commit>.tar.gz` |
| Selected | `policy/*.rst`, `autopkgtest.md`, `debian/copyright` | `man/*.pod`, `man/Makefile.am` |
| Pin | `bcf7ce3c75512efe7274fedf88a8c615483e50872c9fd644c678a816f8b3319b` | `22d4c9ed26c64e136510ae6d7f002b7afb309613223bc88ef025413b8b47e610` |

Licence **GPL-2.0-or-later**, placement **layer**. Evidence: the policy tree's `debian/copyright` (DEP-5) gives
`Files: *` as `License: GPL-2+` and names the exceptions: `copyright-format*.xml` (a preserve-notice licence),
`debconf*` (BSD-3-clause), `fhs-3.0*` (the FHS licence) and some diagrams. None of those are imported, and the
build reads `debian/copyright` and puts each imported document's matching `License:` in its meta (last matching
stanza wins, `*` matches `/`, as DEP-5 says). Every dpkg `.pod` carries "either version 2 of the License, or (at
your option) any later version" in its own header, which the build checks the same way. A document that does not
say so is `see file`.

Group F's notes said the dpkg pages were "roff, POD". At 1.23.12 they are POD only (`man/*.pod`; the roff is
built from them), so no roff reader is needed here; `readers/pod.py` reads them.

## 2. What is read

- Policy: the 12 chapters `ch-*.rst`, the appendices `ap-*.rst`, `upgrading-checklist.rst`, `index.rst` and
  `autopkgtest.md` (DEP-8): 25 documents, 368 sections, 2,202 blocks. Readers: `rst.py` and `markdown.py`.
- dpkg: 63 pages, 524 sections, 2,531 blocks. Reader: `pod.py`. A page's manual section comes from
  `man_MANS` in `man/Makefile.am`, so `deb-control.pod` is `deb-control(5)`; none is unlisted at this pin.

## 3. Refs and numbering

`debpolicy:<doc>[@<commit>]§<section>[#<anchor>][¶<n>]`, and `debpolicy:5.6.1` for a Policy section number.

- A chapter's number is its place in the first `toctree` of `index.rst`: `ch-controlfields` is chapter 5, and its
  sections are `5.1`, `5.6`, `5.6.1`. `debpolicy:5.6.1` therefore needs no document, and `debpolicy:5` is the whole
  chapter. The numbers follow Sphinx's `:numbered:` rule over that toctree (a chapter title is level 1, each
  heading level below it adds one component); they were not compared against the published HTML.
- Appendices (`ap-*`, `upgrading-checklist`) are numbered locally inside their own document. Whether Sphinx's
  appendix numbering continues from the chapters was not checked, so no global appendix number is claimed.
- Policy anchors are the Sphinx labels: `debpolicy:ch-controlfields§s-f-Source`.
- dpkg pages: `debpolicy:deb-control§DESCRIPTION`; `deb-control.5` also works.
- `@<commit>` picks the tree's imported edition (`@aceb1daf`, `@f78cedcd`, or the label `1.23.12`).

## 4. Measured, not CI

2026-11-13, pinned import: policy 26 files selected (530,478 bytes), dpkg 64 (553,089), 0 reader warnings, digests
match, 1.5 MB and 1.3 MB stored.

## 5. Not done

- `copyright-format-1.0.xml` and `debconf_specification.xml` (DocBook XML) are not read; the first is the DEP-5
  specification itself and is the next row.
- dpkg's `doc/spec/*.txt` (triggers, rootless builds, protected fields) are plain text; no plain-text reader yet.
- The policy tree is on salsa; pkgtrust recorded GitLab bot challenges on some Debian hosts. This fetch worked on
  2026-11-13; the `Source` list takes a mirror when one exists (dpkg has the GitHub one, policy has none).
