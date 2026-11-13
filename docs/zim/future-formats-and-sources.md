# Future: more sources and more formats

Status: **ideas recorded 2026-11-07, none started.** Companion to
[future-docs-by-purl.md](future-docs-by-purl.md). The ROADMAP section "Future" carries one row per item.

## 1. Linux man pages and GNU info

What Kiwix already has (catalogue, 2026-11-07):

| ZIM | Size | Articles | Notes |
|---|---|---|---|
| `devdocs_en_man` (2026-10-01) | 29.6 MB | 12,626 | paths like `man1/ls.1`; **measured**: 12,626 articles converted in 19 s with 0 errors and 130,127 code fences for 130,127 `<pre>` blocks (`scripts/measure_conversion.py`, not CI) |
| `www.mankier.com_en_all` (2026-10-27) | 182.9 MB | 72,069 | not downloaded or measured |
| `devdocs_en_bash`, `gnu-make`, `gnu-fortran`, `gnuplot`, `gnu-cobol` | 0.6 to 0.8 MB each | | GNU tools as DevDocs ZIMs |
| `archlinux_en_all`, `gentoo_en_all`, `alpinelinux_en_all`, `unix.stackexchange.com_en_all` | 38 MB, 96 MB, 3 MB, 1.3 GB | | wiki and Q&A, not reference |

A first look at `devdocs_en_man` through zimlore: `outline man --prefix man1/ls` lists `ls (1)`, `ls (1p)`, ...;
the query "recursively list directory contents sorted by size" returned `dir`, `vdir`, `ls`. Two defects seen: the
search excerpt for man pages is chrome ("Pages that refer to this page", a man7.org URL), and a page's section
number is part of the title only. Both are cheap to fix and belong with section-level hits (ROADMAP
`zl.search_single_page_zims`).

**Gaps:** a catalogue search for "gnu manual", "tldr" and "linux kernel" returned nothing, so GNU **info** manuals
(coreutils, glibc, binutils, gcc, emacs), the tldr pages and the kernel documentation are not in Kiwix. Texinfo
can be rendered to HTML, which would put info on the same path as Sphinx and Javadoc in the purl sketch (a
producer builds a ZIM, zimlore reads it). Whether the distribution's own info and man sources can be rendered
reproducibly was **not checked**, and the licence of each manual (GNU FDL, with variations) must be read per
manual before any ZIM is shared; building for local use is a different act from distributing.

## 2. Other formats, starting with CHM

CHM (Microsoft Compiled HTML Help) is the format a lot of older Windows and vendor SDK documentation still ships
in, and Kiwix has nothing for it. Looking only at PyPI today: `pychm` 0.8.6 (licence field "GPL"; not installed
or tried). **Correction:** `chm` 1.5.0, which I first listed beside it, is the Canadian Hydrological Model's
Python tools, not a CHM reader (see `research-producer-and-more-zims.md`). The container format, its compression and its
table-of-contents files are **not researched** in this repository; the first step of any CHM work is reading the
format description and testing a reader against real files, not trusting this paragraph.

Proposed shape, same as the purl producer: a CHM is a *source format*, converted to HTML, then to a ZIM that
zimlore already serves. It does not belong in zimlore itself, whose rule is that it reads ZIMs and never touches
other formats or the network. Candidate sources of the same kind: Windows Help and vendor SDK manuals (CHM),
Javadoc and Doxygen trees, Sphinx and MkDocs builds, EPUB and PDF manuals (PDF being the hard one: layout, not
structure). Each is a `source -> HTML -> ZIM` adapter plus a coverage report that says "cannot convert" rather
than emit an empty ZIM.

**On forge scaffolding.** `D:\code\AGENTS.md` says a plan directory is a document, not a shell: creating a
`pyproject.toml` ahead of its wave "turns a plan into a shell nobody maintains". So the recommendation is to
keep this as a written plan until the maintainer decides to build it, and then create **one** producer repository
for all source formats (purl, CHM, texinfo, Javadoc, Sphinx) rather than one per format. If it is built, it is a
reference-library companion (`PORTFOLIO.md` §4, not tiered, not counted against the two-project rule), and the
name needs the usual `names.py` check; none has been run.

## 3. Priorities as I would order them

1. Section-level search hits (fixes one-page ZIMs and the man-page excerpts; measurable with the eval).
2. The purl producer for Maven Javadoc and Sphinx, because version-exact sources exist for both.
3. Texinfo (info) and CHM adapters, as separate additions to the same producer.
