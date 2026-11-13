# pep: Python Enhancement Proposals

`pep` serves the PEPs in python/peps at a pinned commit, read as reStructuredText: PEP 440 (versions), 427 and 491
(wheels), 517 and 660 (builds), 621 (metadata), 751 (lock files) and the other 740. Every Python project in the
workspace cites them.

Install: `pip install "primarysource[pep,mcp]"`. Import: `primarysource pep import` (one request, 7 MB).
Serve: `primarysource mcp --collection pep`. Tools: `pep_read`, `pep_outline`, `pep_search`, `pep_cite`,
`pep_docs`, `pep_status`.

## 1. Source, pin and licence

| | |
|---|---|
| Repository | python/peps, `peps/` |
| Edition | `main` at commit `155e5bee7d985ef30555b496eb994d24a591f70b` (2026-11-12), label `main 2026-11-12` |
| Fetched from | `codeload.github.com/python/peps/tar.gz/<commit>` (7,141,479 bytes); mirror `github.com/python/peps/archive/<commit>.tar.gz`, which redirects to codeload (a listed host) |
| Pin | manifest digest of the 761 selected files, `6d4a01026a0a2c4b81ecb18d6e23939cc6ba59f6ffc41b7f3d614238951343e8` |
| Licence | **per document.** The repository has no `LICENSE` at its root (the raw URL answers 404). Each PEP's own "Copyright" section is the statement |
| Placement | **layer**, with the per-document caveat below |

Measured over the 747 `pep-NNNN.rst` files at the pin: 246 say "placed in the public domain or under the
CC0-1.0-Universal license, whichever is more permissive" (`public-domain-or-cc0`); 467 say "public domain" in other
words (`public-domain`); 6 name the Open Publication License (`open-publication-license`); 28, the oldest, carry no
statement (`unstated`). The 14 appendix files are `see-parent-pep`. Group F's note ("public domain/CC0 (m)") was
right for most and wrong for those 34: the meta `licence` of each document records which it is, so a placement
decision can be made per document. Whether to withhold the 34 from an image is for the owner.

## 2. What is read

`peps/pep-NNNN.rst` and `peps/pep-NNNN/*.rst`. Reader: `pkgdocs/readers/rst.py` (proposed core reader
`cl.reader_rst`). The RFC 822 style header (`PEP:`, `Title:`, `Status:`, ...) is block 1 of section `0` and fills
the document's meta; the body is reStructuredText. Levels follow the order headings first appear, as docutils
does; the unit is a **block**. Directives are one block written `[name] args`; `.. include::` is inert text.

## 3. Refs

`pep:<n>[@<commit>]§<section>[#<anchor>][¶<n>]`

- `<n>` is the PEP number without leading zeros: `pep:440`. `pep-0440` and `0440` work; `440/appendix-examples`
  names an appendix file.
- `pep:440§Version scheme` is section 3. `pep:440§3.1` is "Public version identifiers". `pep:440§0¶1` is the header.
- `pep:440§version-scheme` (the slug) also works.

## 4. Measured, not CI

2026-11-13: 761 documents, 15,476 sections, 64,766 blocks, 0 reader warnings, 14.8 MB selected, 41 MB stored with
the index, digest matches the pin, 1.9 s.

## 5. Not done

- Section anchors that RST roles make (`:pep:`) are text, not links: a cross-reference graph between PEPs is a row.
- Sphinx labels outside headings are not collected.
- PEP 0 is read like any other file; its generated tables are not in the source tree.
- The tree is `main`, not a release: a new import needs a new pin.
