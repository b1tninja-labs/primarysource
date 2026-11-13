# rpmdocs: rpm's manual and manual pages

`rpmdocs` serves `docs/` of rpm-software-management/rpm at a pinned release: the manual (`format_v4`, `format_v6`,
`tags`, `spec`, `macros`, `dependencies`, `signatures_digests`, ...) and the manual pages (`rpm(8)`,
`rpm-macros(7)`, `rpm-queryformat(7)`, ...). It is the primary text for the rpm format in `pkgformats` and
`pkgtrust`.

Install: `pip install "primarysource[rpmdocs,mcp]"`. Import: `primarysource rpmdocs import` (one request, 1.2 MB).
Serve: `primarysource mcp --collection rpmdocs`. Tools: `rpmdocs_read`, `rpmdocs_outline`, `rpmdocs_search`,
`rpmdocs_cite`, `rpmdocs_docs`, `rpmdocs_status`.

## 1. Source, pin and licence

| | |
|---|---|
| Repository | rpm-software-management/rpm, `docs/` |
| Edition | tag `rpm-6.1.0-release`, commit `f832c7e69945248dd5bcfcacfd10c176ee300fa2` (2026-08-20) |
| Fetched from | `codeload.github.com/rpm-software-management/rpm/tar.gz/<commit>` (1,215,057 bytes); mirror `github.com/.../archive/<commit>.tar.gz` |
| Pin | manifest digest of the 74 selected files, `610c31cafa342d40c7dd3e507749c1fc90fa32c3550d6b8a3e440f45b4a037b7` |
| Licence | **GPL-2.0-or-later.** `COPYING`: "In SPDX terms, the entire code base is licensed GPL-2.0-or-later, with the exception that all of the source code in the lib and rpmio subdirectories ... may instead be considered licensed LGPL-2.0-or-later". `docs/` is in neither of those directories and its files carry no licence of their own |
| Placement | **layer** |

Group F's note recorded "GPL-2.0+ (m), Markdown". The licence is confirmed; the format is two: Markdown for the
manual and **scdoc** for the manual pages (`docs/man/*.scd`), which needed its own small reader
(`pkgdocs/readers/scdoc.py`).

## 2. What is read

`docs/manual/*.md` (Jekyll front matter, whose `title:` becomes the document title, for example "rpm.org - RPM
Tags") and `docs/man/*.<n>.scd`: 74 documents, 669 sections, 2,369 blocks. `docs/man/index.md`,
`docs/index.md.in` and the build files are not read. The unit is a **block**: a paragraph, a fenced block, a table,
a top-level list item with its nested items.

## 3. Refs

`rpmdocs:<doc>[@<commit>]§<section>[#<anchor>][¶<n>]`

- A manual document is its file name without `.md`: `rpmdocs:tags§Tag types`, `rpmdocs:format_v6§Header`.
- A manual page is `<name>.<section>`: `rpmdocs:rpm-queryformat.7§SYNTAX`; `rpm-queryformat` alone also works.
- Markdown anchors are GitHub-style slugs, duplicates suffixed `-1`; that is the rule used here, not a claim about
  CommonMark.

## 4. Measured, not CI

2026-11-13: 74 documents, 669 sections, 2,369 blocks, 0 reader warnings, 353 KB selected, 1.1 MB stored, digest
matches the pin.

## 5. Not done

- scdoc inline markup (`*bold*`, `_underline_`) is left as written, so a quoted option reads `*--queryformat*`.
- Links between manual pages (`[text](other.md)`) are left as text; a link graph is a row.
- `docs/librpm` (Doxygen headers) is not read.
