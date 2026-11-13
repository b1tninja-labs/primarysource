# pms: the Gentoo Package Manager Specification

`pms` serves the Package Manager Specification of Gentoo at a pinned EAPI release, read from its LaTeX source as one
numbered document. It is the primary text for the ebuild and repository formats in `pkgformats` and `pkgtrust`.

Install: `pip install "primarysource[pms,mcp]"`. Import: `primarysource pms import` (one request, 77 KB).
Serve: `primarysource mcp --collection pms`. Tools: `pms_read`, `pms_outline`, `pms_search`, `pms_cite`,
`pms_docs`, `pms_status`.

## 1. Source, pin and licence

| | |
|---|---|
| Repository | gentoo/pms (the root: `pms.tex` and the chapters) |
| Edition | tag `eapi-9-approved-2026-06-14`, commit `2cee9c6bd86851738e8ba1874ac622cfcec70969` |
| Fetched from | `codeload.github.com/gentoo/pms/tar.gz/<commit>` (76,658 bytes); mirror `github.com/gentoo/pms/archive/<commit>.tar.gz` |
| Pin | manifest digest of the 23 selected `.tex` files, `c302537c3d04c28a69b3e4fae19247f168913a29beff587e2e26d6af08d62502` |
| Licence | **CC-BY-SA-4.0.** The title page of `pms.tex`: "released under the Creative Commons Attribution-ShareAlike 4.0 International licence", (c) 2007-2026 Stephen Bennett, Ciaran McCreesh and others |
| Placement | **layer, with attribution**: every citation carries "CC BY-SA 4.0, Stephen Bennett, Ciaran McCreesh and others"; the licence line is in `pms_status` |

**Correction to group F:** their note says CC-BY-SA 3.0, "read on the EAPI 3 page". The current source says 4.0. The
share-alike condition is the same, and a layer that carries a derived form (this collection stores a reduced
text) must keep the licence line and the credit.

GLEPs, the other half of the brief, are not here. `gitweb.gentoo.org/data/glep.git/snapshot/...` answered HTTP 502
twice on 2026-11-13 and there is no GitHub mirror (`gentoo/glep` and `projg2/glep` do not exist). ROADMAP row
`col.gentoo_glep`.

## 2. What is read

`pms.tex` and the 22 other `.tex` files it includes, read from the archive's own files (never from disk) into the
single document `pms`: 172 sections, 993 blocks. Reader: `pkgdocs/readers/latex.py`, a structure reader and not a
TeX engine. Sections are numbered as the typeset text is: chapters 1 to 14, the starred Glossary (unnumbered, id `u1`), then A to F after `\appendix`. A
`\label{...}` after a heading is the anchor, and `\ref{...}` in the text is replaced by the number it names.
Description and list items are blocks (`TERM: text`), `verbatim`, `listing`, `algorithm` and table environments are
one block each written `[environment]` and the raw text. The text between the preamble and the first chapter (the
copyright and licence notice) is section `0`.

The reader reduces markup (`\t{x}` to `x`, `\cite{k}` to `[k]`, dashes) and does not interpret math or the class
file's macros. The document carries one warning listing the commands whose arguments were kept and the command
dropped (for example `featureref`, `href`, `ifthenelse`), so a reader knows the text is a reduction, not a typeset
copy: for the exact table layout, use the PDF.

## 3. Refs

`pms:<doc>[@<commit>]§<section>[#<anchor>][¶<n>]`, and `pms:7.3.1` for a section number.

- `pms:7.3.1` is "EAPI" (section 7.3.1 of this edition); `pms:7` is chapter 7, "Ebuild-defined variables".
- `pms:pms§ch:ebuild-vars` is the same chapter by its LaTeX label; `pms:pms§Mandatory ebuild-defined variables`
  by heading.
- Numbers are this edition's; a different EAPI edition renumbers. Pin the edition in the ref: `pms:7.3.1@2cee9c6`.

## 4. Measured, not CI

2026-11-13: 1 document, 172 sections, 993 blocks, 1 reader warning, 288 KB selected, 0.6 MB stored, digest matches
the pin.

## 5. Not done

- GLEPs (above).
- `\ref` to tables, algorithms and listings is left as its label key; only section labels are numbered.
- The EAPI differences table (`eapi-differences.tex`, `eapi-cheatsheet.tex`) is read as text; its layout is lost.
- A section whose text is a table has the table as raw LaTeX.
