# gm: GM's 2017 OBD parameter files, from the owner's own copies

Recorded 2026-11-15. The owner has 14 PDFs of GM's 2017 OBD diagnostic parameter files and Mode $06 definitions
(in `D:\Research\volt\GM\`) and wanted them searchable and citable. This records where they go, the licence
posture, how a table PDF is cut, what a search hit looks like, and what a trial on the real files found.

```
pip install "primarysource[gm,mcp]"                 # pypdf, needed only to import; mcp to serve
primarysource gm import D:\Research\volt\GM         # a folder of PDFs, a single PDF, or no path: the gm home
primarysource gm search "P0010"
primarysource gm read "gm:17OBDG01-hybrid§p1"
primarysource mcp --collection gm                   # gm_read, gm_search, gm_outline, gm_cite, gm_docs
```

Every command above refuses until `PRIMARYSOURCE_GM_ACCEPT_TERMS` is set by the owner: see `docs/terms-gate.md`.

## 1. Placement and licence posture

- **Local only.** The files stay where the owner keeps them. Nothing here fetches, the PDFs are never copied (the
  import stores the extracted text and a record of the source), and no document text is in this repository or any
  image. This is the placement `docs/iso.md` §2 gives for purchased PDFs, applied to a different publisher.
- **Home.** `$PRIMARYSOURCE_GM_HOME`, else `$PRIMARYSOURCE_HOME/gm`, else `%LOCALAPPDATA%\primarysource\gm`. The
  import writes `extracted/`, `index.sqlite` and `install.json` there. The PDFs may stay elsewhere: pass their folder
  to `import`.
- **Licence.** The first pages of the files carry no copyright line, no GM statement and no licence
  (`docs/local-source-survey.md` §4). GM publishes them for the aftermarket under the CARB/EPA service-information
  rules, but that is a statement of why GM publishes them, not a grant to redistribute. **GM's terms URL was not
  verified**, so the gate passes `None` and its error names no page. The owner reads GM's terms for these files and,
  if they accept them, sets `PRIMARYSOURCE_GM_ACCEPT_TERMS=1`.

## 2. Documents

Document ids come from the file names (`gm.name_file`):

| File | Document | Pages |
|---|---|---|
| `17OBDG01 Hybrid Diagnostics.pdf` | `gm:17OBDG01-hybrid` | 1,887 |
| `17OBDG02 Hybrid Diagnostics.pdf` | `gm:17OBDG02-hybrid` | 1,717 |
| `17OBDG03 Engine Diagnostics.pdf` | `gm:17OBDG03-engine` | 1,781 |
| `17OBDG03 Transmisson Diagnostics.pdf` | `gm:17OBDG03-transmission` | 711 |
| `17OBDG03 Transmisson Diagnostics (1).pdf` | the same document (byte duplicate) | 711 |
| `17OBDG04 Engine Diagnostics.pdf` | `gm:17OBDG04-engine` | 1,484 |
| `17OBDG04 Transmisson Diagnostics.pdf` | `gm:17OBDG04-transmission` | 346 |
| `17OBDG05 Engine Diagnostics.pdf` | `gm:17OBDG05-engine` | 107 |
| `17OBDG05 Transmission Diagnostics.pdf` | `gm:17OBDG05-transmission` | 56 |
| `17OBDG06 Engine Diagnostics.pdf` | `gm:17OBDG06-engine` | 130 |
| `17OBDG06 Transmission Diagnostics.pdf` | `gm:17OBDG06-transmission` | 56 |
| `2017_OBD_GROUP_SUMMARY.pdf` | `gm:2017-group-summary` | 5 |
| `GM CAN mode $06 data final_dm.pdf` | `gm:mode6-can` | 36 |
| `GM Class2 mode $06 data final_dm.pdf` | `gm:mode6-class2` | 16 |

GM's own file names spell `Transmisson` in two files and `Transmission` in the rest; both give `-transmission`. The
two `17OBDG03 Transmisson Diagnostics` files have the same bytes. The import keeps the one without a copy marker
(`(1)`) and reports the other as `skipped duplicate of gm:17OBDG03-transmission`, however the names sort. A file name
the collection does not know is skipped with that reason, never guessed at. A second file for the same document with
different bytes is skipped as `already taken by another file with other bytes`.

## 3. Cutting a table PDF

The parameter files are tables with no bookmarks and no numbered clauses, so the shared splitter
(`readers.bookmarks.cut_numbered`) finds nothing and refuses them. The collection asks the reader for the page cut
instead (`pages_per_section=1`, `readers.bookmarks.cut_pages`):

- **One section per page.** The id is `p<page>` (`p12`); a PDF page with no text after furniture is left out. A
  section's `depth` is 0 and `page` its PDF page.
- **The unit is a text line**, so `¶n` counts lines and the footer says `unit: block` (`model.Unit.BLOCK`). A table
  row has no sentence ends, so the sentence splitter would have run a whole page together. This changes one thing from
  the sentence units the `iso` collection uses: `gm` declares blocks, `can` (prose) keeps sentences.
- **Text comes from `pdftotext -layout`** when it is on PATH (poppler or Xpdf), so a row's cells stay on one line;
  otherwise from pypdf's layout mode. A run of two or more spaces, a column gap, is written ` | `.
- **Furniture is dropped**: a line that repeats on a quarter of the pages (the column-header row, `Section 12 of
  481`) is removed, as `readers.bookmarks.clean_pages` does for any PDF.
- **A title** is the fault codes on the page (`P0010, P0011`, at most four and `(+n)`), found by the pattern
  `[PBCU][0-3][0-9A-F]{3}`; a page with none (a supporting table, a continuation) takes its first line of text, at
  most 80 characters.

A search hit is one section per line, `<ref>  <title>: <snippet>`:

```
gm:17OBDG03-engine§p1  P0010, P0011: ... Valve circuit open | 5 volts ...
gm:17OBDG03-engine§p3  Supporting table | Gasket pressure | 40 kPa: ...
```

(the text is invented, as in the tests). `gm:17OBDG03-engine§p1` reads the page; `...§p1¶2` starts at its 2nd line;
`gm:17OBDG03-engine` reads every page in turn with a `next:` ref. A fault code such as `P0010` is found by search
because the page's body is indexed whole.

`pdfcorpus` was not reused for this: it is the skeleton of a fetched corpus (a fetch command, a download directory,
revisions). The volume here is `primarysource/localpdf/`, derived from `primarysource/iso/` without its designation
logic and shared with `can`. The reader's page and size bounds (`MAX_PAGES` 2,000, `MAX_BYTES` 64 MiB) already cover
the largest file (1,887 pages, 5.8 MB), so they were not raised.

## 4. Trial on the real files (2026-11-15, nothing imported)

A scratch script called `readers.pdf.extract` (the reader the importer uses, with `pdftotext 4.00`) directly on each
file. It did not call the importer, did not set `PRIMARYSOURCE_GM_ACCEPT_TERMS`, created no collection home and wrote
only to a scratch folder outside the repository, since deleted.

| File | Pages | Sections | Time | Peak memory | Lines |
|---|---|---|---|---|---|
| 17OBDG01 Hybrid | 1,887 | 1,887 | 2.8 s | 67 MB | 44,658 |
| 17OBDG02 Hybrid | 1,717 | 1,717 | 2.5 s | 62 MB | 42,066 |
| 17OBDG03 Engine | 1,781 | 1,780 | 2.6 s | 63 MB | 41,337 |
| 17OBDG03 Transmisson (and its copy) | 711 | 711 | 1.5 s | 59 MB | 30,453 |
| 17OBDG04 Engine | 1,484 | 1,484 | 2.1 s | 59 MB | 33,797 |
| 17OBDG04 Transmisson | 346 | 346 | 0.7 s | 44 MB | 9,912 |
| 17OBDG05 Engine | 107 | 107 | 0.5 s | 42 MB | 6,424 |
| 17OBDG05 Transmission | 56 | 56 | 0.3 s | 40 MB | 2,355 |
| 17OBDG06 Engine | 130 | 130 | 0.5 s | 43 MB | 7,558 |
| 17OBDG06 Transmission | 56 | 56 | 0.3 s | 40 MB | 2,398 |
| 2017_OBD_GROUP_SUMMARY | 5 | 5 | 0.2 s | 38 MB | 122 |
| GM CAN mode $06 | 36 | 36 | 0.3 s | 43 MB | 1,436 |
| GM Class2 mode $06 | 16 | 16 | 0.2 s | 38 MB | 449 |

All 14 files read with segmenter `pages`, no failure, and **no page without a text layer** (no scans). The one page
missing from a section list is page 333 of 17OBDG03 Engine, which holds only its header and footer. The PDFs'
title metadata is useless (`Microsoft Word - CBI_HGMXOBDG01_A_L.docx`, `A9Rgmcvwq_xl4pt3_bt8.tmp`), so the collection
names each document itself.

What the extractor could **not** handle well, and what to expect in the text:

- **A cell that wraps over several lines is not kept together.** The line is cut across the row, so the text of one
  cell is spread over consecutive lines, each shared with the neighbouring cells' lines. Reading a parameter's
  malfunction criteria or enable conditions means reading down a column. Rows are on one line only when every cell is
  a single line. The tables are not reconstructed into cells.
- **Header residue.** The column-header row is dropped as furniture, but where its second line shares a text line with
  a body cell, a fragment survives at the top of a page (`System | Code Description | 20`, `to Use | to Use`).
- **Symbol glyphs arrive as control characters.** Comparison and unit symbols in a symbol font (apparently the
  greater-or-equal, less-or-equal and degree signs, and bullets) come out as C1 control characters (U+0080 to U+009F,
  for example 1,077 in 17OBDG01 and 1,440 in 17OBDG03 Engine) or as stray letters. They are not mapped back, because
  which symbol each stands for was not established. The meaning of a `>=`-style threshold may therefore be lost in the
  text; check the PDF for any value that matters.
- **Mode $06 tables misalign.** In the two Mode $06 files the ID columns and the description drift onto separate
  lines (`01 | 24 | ...` then `D0 | ...`), so a Test ID and its description can be a line apart.
- **Supporting tables lose their row labels.** A numeric grid keeps its numbers but the row and column axes can end up
  on different lines.
- **About 9 to 35% of pages have no fault code** (322 of 1,887 pages in 17OBDG01, 514 of 1,484 in 17OBDG04, 10 of 107 in 17OBDG05 Engine):
  continuations and supporting tables, titled by their first line instead.
- **Not tested here:** the no-`pdftotext` path on the real files (pypdf's layout mode, slower, and it raises on a page
  with no content stream, which the reader now reads as empty), and an import through the gate, because the variable
  is the owner's to set.
