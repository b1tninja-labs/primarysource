# gitdocs: git's Documentation

`gitdocs` serves the `Documentation/` tree of git/git at a pinned release: the manual pages, the `gitformat-*` and
`gitprotocol-*` specifications, the `technical/` notes, the how-tos and the release notes. It is the
authoritative text for the pack format, the protocols and `git patch-id`, for `gitobj` and `pkgtrust`.

Install: `pip install "primarysource[gitdocs,mcp]"` (the extra adds nothing; the importer is standard library).
Import: `primarysource gitdocs import` (one HTTPS request, about 2 MB, a second). Serve:
`primarysource mcp --collection gitdocs`. Tools: `gitdocs_read`, `gitdocs_outline`, `gitdocs_search`,
`gitdocs_cite`, `gitdocs_docs`, `gitdocs_status`.

## 1. Source, pin and licence

| | |
|---|---|
| Repository | git/git, `Documentation/` |
| Edition | tag `v2.56.1`, commit `03b41523c576f26ad34085378717a0c1b287470f` (2026-10-23) |
| Fetched from | gitiles subtree archive `kernel.googlesource.com/pub/scm/git/git/+archive/<commit>/Documentation.tar.gz` (1.9 MB). Mirror: the GitHub tarball `codeload.github.com/git/git/tar.gz/<commit>` (54 MB tar), read with `subdir="Documentation"` |
| Pin | manifest digest of the 951 selected files, `3a6d1e943dd8fe4aff27ffb5c4c0949a5a0f170b35a1413aecf4ae62e208a9bb` |
| Licence | **GPL-2.0-only**, read from `COPYING` at the repository root: "the only valid version of the GPL as far as this project is concerned is _this_ particular version (ie v2, not v2.2 or v3.x)". `COPYING` is outside the subtree archive, so it is named as evidence, not read by the importer |
| Placement | **layer** (image). GPL asks that the licence and the source stay available; `gitdocs_status` and the pin say where they are |

The pin is the manifest of the **selected files** (`pkgdocs/fetch.py::manifest_digest`), not a digest of the archive:
two fetches of the same gitiles archive differ byte for byte (measured 2026-11-13: 7,508,480 and 7,514,624
decompressed bytes, because gitiles stamps each header with the time of the request), and the GitHub tarball is a
third byte stream. The manifest is the same from all of them; the mirror was read once and gave the identical digest.

## 2. What is read

Every `*.adoc` under `Documentation/` (951 files): 3,630 sections and 30,031 blocks. `.adoco` files, scripts,
stylesheets and the plain-text `CodingGuidelines` and `SubmittingPatches` are not read (rows below).

Reader: `pkgdocs/readers/asciidoc.py` (private; proposed core reader `cl.reader_asciidoc`). Sections come from
`=` headings or `-`, `~`, `^`, `+` underlines. The unit is a **block**: a paragraph, a delimited block, a table, or a
labelled-list term or list marker with its text. `include::` is never read; it becomes `[include] <path>`.
`ifdef::` lines are dropped and their content kept, and the 30 documents that had any carry a warning with the count.

## 3. Refs

`gitdocs:<doc>[@<commit>]§<section>[#<anchor>][¶<n>]`

- `<doc>` is the path without `.adoc`: `gitformat-pack`, `git-config`, `technical/commit-graph`, `RelNotes/2.50.0`.
- `<section>` is an ordinal id (`6`, `5.4`), an anchor (an explicit `[[id]]`, else the slug), a heading, or a unique
  part of a heading. Trailing `:` and `.` are ignored.
- `¶n` is the nth block of that section.

Examples, all read against the real import:

- `gitdocs:gitformat-pack@03b4152§pack-*.idx files have the following format` resolves by unique part to section 6,
  "Original (version 1) pack-*.idx files have the following format:". The brief's heading is not verbatim in this
  edition, which is the reason a unique part is accepted; `@03b4152` pins the edition.
- `gitdocs:gitformat-pack§6¶1` is the first block under it.

## 4. Measured, not CI

`primarysource gitdocs import`, 2026-11-13, into `D:\temp\...\collections4\home_final`: 951 documents, 3,630
sections, 30,031 blocks, 30 reader warnings (all `ifdef`), 5,577,354 bytes selected, 16.1 MB stored with its index,
digest matches the pin, 1.3 s. The test suite never touches the network: `tests/test_pkgdocs_asciidoc.py` and
`tests/test_pkgdocs_collections.py` run on invented text.

## 5. Not done

- `include::` expansion (the included file is its own document, so a page's text is not whole).
- Plain-text `CodingGuidelines`, `SubmittingPatches`; `.adoco` generated includes.
- Manual-page section for a page is read from its title `name(N)`; `git.adoc` and non-man documents have none.
- The git tree hash of `Documentation/` is not checked against the commit (needs `gitobj`; see `docs/pkgdocs.md`).
