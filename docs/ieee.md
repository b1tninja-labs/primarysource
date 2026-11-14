# IEEE collections: `posix` and `ieee802`

Two collections in one subpackage, `primarysource/ieee/`, both installed by one extra:

```
pip install "primarysource[ieee]"
primarysource posix import susv5.tgz          # your own download, see section 4
primarysource mcp --collection posix            # tools posix_read, posix_outline, posix_grep, posix_pages
primarysource mcp --collection ieee802          # tool ieee802_outline
```

The repository holds **no IEEE or Open Group text**: only code, the catalogue (designations, titles, URLs, sizes
and sha256 digests) and invented test pages. Text you import lives under `$PRIMARYSOURCE_HOME/posix/` and
`$PRIMARYSOURCE_HOME/ieee802/`, for your personal use.

## 1. What the collections cover

| Collection | Covers | Source | Unit of `¶n` |
|---|---|---|---|
| `posix` | IEEE Std 1003.1-2024 | the free HTML edition from The Open Group | block |
| `ieee802` | IEEE 802 standards | PDFs from the IEEE GET Program | sentence |

**POSIX is one edition with three designations.** The same text is published as:
- IEEE Std 1003.1-2024;
- The Open Group Base Specifications Issue 8;
- ISO/IEC/IEEE 9945: the second edition is 9945:2026 (replacing the 2009 first edition). IEEE's own page for
  1003.1-2024 (standards.ieee.org, read 2026-11-13) lists the ISO/IEC/IEEE 9945 standard with the same Issue 8
  title. The 2026 year and the March 2026 date come from search-result snippets only (iso.org answered HTTP 403
  to an automated fetch), so they are not verified from the primary page. The ISO edition is sold and is not
  imported here.

IEEE publishes the 2024 edition as "IEEE/Open Group Standard for Information Technology--Portable Operating
System Interface (POSIX) Base Specifications, Issue 8", designation IEEE 1003.1-2024, an Active Standard
published 2024-06-14 (standards.ieee.org, read 2026-11-13). A cite names IEEE first, then Issue 8, because the
IEEE designation is the one the standard is published under. The edition id `posix-2024` is the year of
IEEE Std 1003.1-2024; an earlier edition (`posix-2017`) is not catalogued and is refused as not imported.

The collection holds the HTML edition: four volumes, XBD (`basedefs/`), XSH (`functions/`), XCU (`utilities/`)
and XRAT (`xrat/`), plus front matter, index and help pages.

**IEEE 802** standards are free through the IEEE GET Program, which per the research notes opens a standard six
months after publication (not re-verified here). The catalogue lists two editions, read from their
standards.ieee.org pages on 2026-11-12: 802.1Q-2022 and 802.3-2022. The GET listing itself
(ieeexplore.ieee.org) answered HTTP 418 to an automated fetch, so more entries need a person to read it.

**Out of reach:** paid standards. IEEE 754, 1588 and 1284 are sold, not in the GET Program as far as the
searches showed; ISO/IEC/IEEE 9945 is sold too. Nothing here buys, borrows or works around that.

**Why two collections and not one.** Licence, placement and pin are per collection (PLAN.md §5.4, §5.8), and
the two publishers' terms differ: The Open Group's terms for POSIX, IEEE's GET terms for 802.

## 2. Licence and terms

**POSIX.** The Open Group's terms page, read 2026-11-12: <https://pubs.opengroup.org/onlinepubs/terms.htm>.
In summary:
- the Base Specifications / IEEE Std 1003.1 are a joint work, and both The Open Group and the IEEE hold
  copyright;
- you may read them and download them for personal use, "provided you have given your name and email
  address";
- you may not amend, copy, reprint, sell or otherwise re-use them without permission from both holders;
- the hard copy is authoritative.

The download page (<https://pubs.opengroup.org/onlinepubs/9799919799/download/>, read 2026-11-12) offers the
archives "for local installation and personal use only". It says that downloading implies agreement with those
terms. It presents no form.

**IEEE 802 (GET Program).** <https://standards.ieee.org/products-programs/ieee-get-program/>, read 2026-11-12:
- you must accept IEEE's Terms and Conditions of Use before the PDF is available;
- the documents are not in the public domain;
- IEEE is the sole copyright holder.

The terms page itself (<https://ieeexplore.ieee.org/Xplorehelp/overview-of-ieee-xplore/get-program-terms-of-use>)
answered HTTP 418 to an automated fetch, so its copy and automation limits are **unverified**. Read them
yourself before importing.

## 3. Placement and the catalogue

Both collections are **volume, never image**. Neither text may be baked into a container image or shipped in a
wheel. A shared server reads it from a mounted volume that holds your own import.

`primarysource/ieee/catalogue.json` is package data. For each collection it records:
- the licence id: `LicenseRef-OpenGroup-IEEE-personal-use` or `LicenseRef-IEEE-GET-Program`;
- the placement (`volume`);
- the terms URL, the date it was read, and a summary.

For each edition it records the designations, title, publisher, edition date, page URL and source URL, plus the
expected archive name, its size and its sha256. An 802 entry has a `null` sha256 until a file is supplied.
`catalogue.py` exposes the pins as module constants (`POSIX_2024`, `POSIX_TERMS`, `IEEE802_TERMS`), so the core's
manifest can lift them (section 8).

## 4. How you obtain and import each document

Nothing in this package fetches. Giving a name and email address, logging in, or accepting terms is your act,
never the tool's.

**POSIX.** Download `susv5.tgz` (the gzip tar) from the download page above, under its terms, then run:

```
primarysource posix import path/to/susv5.tgz
```

The import:
1. checks the file's sha256 against the pin
   (`11c7ee3e98febe3d58d03a02885d0fab9a3564d06a9b02742d9d138ae341a957`, 4,962,222 bytes) and refuses on a
   mismatch. The error names the cause and says where to download again. Only the `.tgz` is pinned: the
   `.zip`, `.tar` and `.tar.bz2` downloads hash differently and are refused;
2. streams the tarball (`tarfile` mode `r|gz`, no seeking, no `extractall`) and writes only the HTML pages
   under `susv5-html/`. It skips symlinks, images, scripts and stylesheets;
3. refuses the whole import, leaving nothing installed, on any of:
   - a member with an absolute, `..`, backslash or drive-letter path;
   - a page over 4 MB;
   - more than 10,000 members;
   - more than 200 MB of pages;
   - an archive over 64 MB;
4. writes into a staging directory, then renames it to `$PRIMARYSOURCE_HOME/posix/posix-2024/` with an
   `install.json` record. A reader sees the old edition or the new one, never half of one.

**IEEE 802.** Obtain the PDF yourself through the GET Program, then run:

```
primarysource ieee802 import file.pdf 802.1Q-2022
```

`IEEE Std 802.1Q-2022` is accepted as the designation too. The import:
- refuses a designation the catalogue does not list, a file that does not start with `%PDF-`, and an encrypted
  PDF. It never decrypts;
- needs `pypdf`, from the `[ieee]` extra. Without it, the error names `pip install "primarysource[ieee]"`;
- stores the bookmarks (with clause numbers) and the page text under `$PRIMARYSOURCE_HOME/ieee802/<designation>/`.

No 802 digest is pinned yet, so the first import records the file's sha256 in `install.json` (trust on first
use) rather than checking it.

## 5. Ref grammar and unit

Both use the core's `RefGrammar` (`<doc>§<section>[#anchor][¶n]`; `::` is the ASCII spelling of `§`).

**posix**:
- `posix-2024§functions/open` is a whole page;
- `posix-2024§functions/open#tag_17_372_03` is the section under one heading;
- `posix-2024§functions/open#tag_17_372_03¶2` is one block of that section.

The parts:
- The document is the edition, `posix-[0-9]{4}`.
- `§` names a page by its path without `.html`: `functions/open`, `utilities/pax`, `basedefs/stdio.h`,
  `basedefs/V1_chap03`. `utilities/[` is the one page whose name starts with `[`.
- `#` names an HTML anchor on that page: The Open Group's own `tag_…` ids, which are stable within an edition.
  An id that sits just before a heading (`#open` on `functions/open`) finds that heading.
- A bare `functions/open#tag_17_372_03` reads the 2024 edition.

**Unit: block.** A block is what the HTML converter emits: a paragraph, a list item, a code block, a table or a
definition term. `¶n` counts blocks:
- with an anchor: the blocks under that heading, the heading itself excluded and its subsections included;
- with a page only: every block of the page, headings included.

The HTML has real paragraphs, but it also has lists, tables and code, so block is the honest unit.

**ieee802**: `802.1Q-2022§5.4¶2`.
- The document is the standard by number and year: `802(\.[0-9]+[A-Za-z]*)*-[0-9]{4}`, as in `802.1Q-2022`,
  `802.1AB-2016`, `802.15.4-2020` and `802.3bz-2016`.
- `§` is a dotted clause or annex: `5.4`, `A.1`.
- **Unit: sentence.** `¶n` is the nth sentence of the clause's extracted text, because a PDF yields sentences,
  not paragraphs. Clause reading is not built yet (section 7).

## 6. Reading

- **posix**:
  - `posix_outline(page)`: the page's headings, each with its ref.
  - `posix_read(ref, start, max_tokens)`: text paged by the core's `budget.page`. The core's footer follows
    (`cite:`, `unit:`, `span:`, and `next: start=N` when there is more).
  - `posix_grep(text, volume, limit, start)`: one `<ref>: <snippet>` line per matching block. The match is
    literal and case-insensitive. It is bounded by the hit limit (at most 200), a 10-second scan budget and a
    200-character needle, and it resumes with `start`.
  - `posix_pages(volume)`: page ids.
  - A citation reads `IEEE Std 1003.1-2024 (The Open Group Base Specifications Issue 8), XSH open, DESCRIPTION ¶2`.
- **ieee802**: `ieee802_outline(designation)`: the clauses from the PDF's bookmarks, as refs with their pages.
- **Search** waits for the core's FTS5 index (`cl.index_fts5`). No second index is built here.

The same functions run from the command line as `primarysource posix outline|read|grep|pages` and
`primarysource ieee802 outline`.

## 7. Limits and measurements

Measured on the real archive on 2026-11-12, with `tools/ieee_import_posix.py` (opt-in, not a test):

| | |
|---|---|
| members | 1,715 (1,696 files, 11 directories, 8 symlinks) |
| HTML pages | 1,616, totalling 24,248,288 bytes; the largest is 459,326 bytes |
| encoding | UTF-8 on every page (4 declare iso-8859-1 and still decode as UTF-8) |
| import | 0.9 s |
| conversion | every page in 17.8 s; 124,986 blocks and 23,944 headings |
| headings without an anchor | 139: on front-matter, index and contents pages, and on 16 `utilities/` stubs (`break`, `set`, ...) that redirect to the special built-ins chapter |
| other checks | 0 duplicate section ids; 0 truncated pages |

Limits:
- No search, only a bounded grep.
- 802 clause text is not readable yet (`ieee.ieee802_read`). The 802 import has never run on a real GET PDF.
- The converter's ceiling is 4 MB of text per page (zimlore's).
- Anchors are per edition: a future edition renumbers `tag_…` ids.
- The archive is installed as files (one HTML file per page), not read from the tarball on every request. The
  readers open one page file at a time; none unpacks an archive.

## 8. Proposed core changes

This work changes no core module. Two things live privately in `primarysource/ieee/` until the core takes them:

1. **The HTML reader** (`cl.reader_html`). `primarysource/ieee/_html.py` is zimlore's `zimlore/markdown.py`
   (commit 1903b46), copied together with the zimlore tests that pin it:
   - `tests/test_ieee_html_markdown.py`: zimlore's `test_markdown.py`, plus the converter cases from
     `test_hardening.py`;
   - `tests/test_ieee_html_structure.py`: zimlore's `test_converter_structure.py`;
   - `tests/test_ieee_html_regions.py`: zimlore's `test_regions.py`.

   It uses the standard library only (`html.parser`). The one change from zimlore is a `Profile`. The default,
   `GENERIC`, reproduces zimlore's output, which the copied tests pin. `POSIX` adds five rules:
   - two chrome classes, `NAVHEADER` and `topOfPage`;
   - `inner_anchor`: an `<a name id>` that opens a heading names the heading. Without it, every POSIX heading
     loses its anchor;
   - `small_print_centre`: a `<center><font size="2">` banner is furniture;
   - `plain_blockquote`: a blockquote is indentation, not a quotation;
   - `rules`: `<hr>` emits nothing.

   Proposed: lift `_html.py` into the core with zimlore's tests and keep `Profile` as the per-site hook. Then
   zimlore and this collection both import it. zimlore's ROADMAP §10 currently says the converter stays in
   zimlore, so that decision needs revisiting.
2. **The pins** (`cl.collection_manifest`). The manifest needs these fields for these collections:
   - `licence`: an SPDX id or `LicenseRef-…`;
   - `placement`: `layer`, `volume` or `none`;
   - `terms_url` and `terms_read` (a date or a note);
   - per edition: `id`, `designations` (one or more), `title`, `publisher`, `edition_date`, `page_url`, and
     `source_url` (nullable: 802 PDFs have no fetchable URL);
   - per edition: `archive` (the expected file name), `size` and `sha256`. A pin may be null until the user
     supplies a file, and the manifest must say whether a null pin is trust-on-first-use or a refusal;
   - per edition: `root`, the archive's member prefix (`susv5-html/`).

Also for the core:
- `registry.attribute` builds the server install hint as `primarysource[<collection name>,mcp]`. For posix and
  ieee802 that names extras that do not exist. It should use the target's `[extra]` (`ieee`), as `_targets`
  does.
- `home.collection_home` is used through `importer.collection_home`, which only adds an explicit-home override
  for tests.

**Dependencies.** `pypdf>=5`, the `[ieee]` extra, is imported only by the 802 PDF import. `posix` needs nothing
outside the standard library to import or read, and `mcp` only to be served. The rfc collection's extras
(b7ea38e) landed first, so `pypdf` is not this package's first third-party dependency. It is the first one a
document reader needs. The owner's self-sufficiency rule (no third-party runtime dependencies) against optional
extras is still an open question in PLAN.md §7.
