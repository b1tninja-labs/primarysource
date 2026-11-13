# kconfig: the kernel's Kconfig and Kbuild documentation

`kconfig` serves `Documentation/kbuild/` of the Linux kernel at a pinned release, read as reStructuredText. The
Kconfig language reference is `kconfig-language`; `kconfigpy` and `pkgtrust` R165 take their grammar from it. The
macro language, the configuration targets (`make menuconfig` and friends) and the Kbuild documents come with it.

Install: `pip install "primarysource[kconfig,mcp]"`. Import: `primarysource kconfig import` (one request, 57 KB).
Serve: `primarysource mcp --collection kconfig`. Tools: `kconfig_read`, `kconfig_outline`, `kconfig_search`,
`kconfig_cite`, `kconfig_docs`, `kconfig_status`.

## 1. Source, pin and licence

| | |
|---|---|
| Repository | torvalds/linux, `Documentation/kbuild/` |
| Edition | tag `v7.3`, commit `c03c1a14507dfaf8b856c2608f9ac216021fc222` (2026-10-18) |
| Fetched from | gitiles subtree archive `kernel.googlesource.com/pub/scm/linux/kernel/git/torvalds/linux/+archive/<commit>/Documentation/kbuild.tar.gz` (57,258 bytes). No mirror: the GitHub tarball of the kernel is hundreds of MB for fourteen files |
| Pin | manifest digest of the 14 selected files, `36d3fe2bf74fee4efef91f7a16a56297966652812e314f8122eb4e5d0cd13ecd` |
| Licence | **GPL-2.0-only.** `COPYING` says "GPL-2.0 WITH Linux-syscall-note", the note covering the user-space API headers; `Documentation/process/license-rules.rst` says the kernel is "GPL version 2 only" |
| Placement | **layer** |

Only 3 of the 14 files carry an `SPDX-License-Identifier` line (`GPL-2.0-only` once, `GPL-2.0` once on `index.rst`);
the build records the tag as the document's `licence` meta and records the rest as `GPL-2.0-only (COPYING, no file
tag)`. Group F's note said "GPL-2.0 (m)"; it is GPL-2.0-only, and it is the kernel's rule rather than a per-file
statement for most of these files.

## 2. What is read

The `.rst` files of `Documentation/kbuild/`: `kconfig-language`, `kconfig-macro-language`, `kconfig`, `kbuild`,
`makefiles`, `modules`, `llvm`, `gcc-plugins`, `reproducible-builds`, `gendwarfksyms`, `headers_install`,
`bash-completion`, `issues`, `index`. Reader: `pkgdocs/readers/rst.py`. These files use an overlined title, which
the reader promotes to the document title. The unit is a **block**; a literal block after `::` is its own block
(the Kconfig examples are literal blocks, so `¶n` addresses a sample).

## 3. Refs

`kconfig:<doc>[@<commit>]§<section>[#<anchor>][¶<n>]`

- `kconfig:kconfig-language§Menu entries` is section 2; `kconfig:kconfig-language§Menu attributes¶5` is its fifth
  block; `kconfig:kconfig-macro-language§Built-in functions`.
- `§0` of a document is its title section (empty when the file goes straight to a heading, as these do).

## 4. Measured, not CI

2026-11-13: 14 documents, 212 sections, 950 blocks, 0 reader warnings, 166 KB selected, 0.5 MB stored, digest
matches the pin, under a second.

## 5. Not done

- The example `Kconfig.*` files in the directory (`Kconfig.recursion-issue-01`, ...) are plain text and not read;
  the rst documents quote them.
- `Documentation/kbuild/` only. Kconfig-adjacent text elsewhere in the tree (`Documentation/kernel-hacking`,
  `scripts/kconfig/` comments) is out of scope here.
