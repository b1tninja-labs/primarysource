# usbids: the USB ID database

`usbids` is the `usb.ids` file of the linux-usb.org USB ID Repository as a primarysource collection: vendor and
product ids, device classes, subclasses and protocols, HID usages, languages and the other lookup tables. It
names things. It is not a USB specification, and it is not USB-IF's text; the `usb` collection holds the
specifications.

    primarysource usbids import          # one request, into $PRIMARYSOURCE_HOME/usbids/
    primarysource usbids lookup usbids:1d6b:0002
    primarysource usbids search "root hub"
    primarysource usbids classify 09 00 02
    primarysource mcp --collection usbids      # tools usbids_lookup, usbids_search, usbids_classify, usbids_sections

Until the coordinator adds the registry line (below), run the importer as
`python -m primarysource.usbids.importer`; everything else works through `primarysource usbids ...` once registered.

## Sources, researched 2026-11-13

Every claim has the URL it came from and the day it was read.

### The database

| What | Finding | Source, read 2026-11-13 |
| --- | --- | --- |
| Licence | "The contents of the database and the generated files can be distributed under the terms of either the GNU General Public License (version 2 or later) or of the 3-clause BSD License." | `http://www.linux-usb.org/usb-ids.html`, "Download" section |
| File header | **Carries no licence.** Its header is a title, the maintainer (Stephen J. Gowdy), submission instructions, `# Version: 2026.06.26` and `# Date: 2026-06-26 20:34:02`. There is no copyright or SPDX line anywhere in the 25,705 lines. The licence is a statement on the web page, not in the file. | `https://usb-ids.gowdy.us/usb.ids`, first 20 lines |
| GitHub mirror | `github.com/usbids/usbids`, described as "Linux USB ID Repository (master still in CVS at SourceForge.net)"; GitHub labels its LICENSE file GPL-3.0. That disagrees with the page's "GPL 2 or later or BSD-3-Clause". The importer records the page's statement; the disagreement is for the owner to know about, and the BSD-3-Clause option satisfies either reading of "redistributable". | `https://github.com/usbids/usbids`, via a page summary, not the raw LICENSE file |
| Transport | `https://www.linux-usb.org/usb.ids` fails certificate verification (the certificate is for `*.sf.net`), so only plain http is available there. `https://usb-ids.gowdy.us/usb.ids` (the maintainer's host) and `https://raw.githubusercontent.com/usbids/usbids/master/usb.ids` both verify and serve **the same 730,605 bytes**, sha256 `f5a48b0cc8dae1607c2f0bae6b8dc13f2ecef69dbeaeaf34b4be8e280d34dba4`, as the http copy. | curl, 2026-11-13 |
| Cadence | The page says "We generate daily snapshots of the database". Observed: all three hosts serve `Last-Modified: Fri, 26 Jun 2026 20:34:02 GMT`, 4.5 months before the measurement, so the daily snapshot has not changed since June. Treat the cadence as irregular and let the importer's conditional request say whether anything is new. | `usb-ids.html`; response headers |
| Variants | `usb.ids.gz` and `usb.ids.bz2` are linked beside it; not used. | `usb-ids.html` |
| Submissions | Web interface, or patches e-mailed to a robot at linux.usb.ids@gmail.com. Entries are volunteer-submitted. | `usb-ids.html` |

### The format, measured on the 2026-06-26 snapshot

730,605 bytes, 25,705 lines, the longest 160 characters. The file is UTF-8 **with one line in Latin-1** (a `0xB4`
acute accent at about byte 707,385, in the HID usage tables). `file` calls it UTF-8 text; a strict decode fails.
The parser reads a line that is not valid UTF-8 as Latin-1 and counts it (`UsbIds.latin1_lines`).

A line is `<id>  <name>` (two spaces) with zero to two leading tabs; one name has three spaces, which the parser
trims. `#` is a comment and the first ones carry `# Version:` and `# Date:`. Column-zero lines are vendors or a
section record led by a tag:

| Tag | Section | Levels | Entries (2026-06-26) |
| --- | --- | --- | --- |
| none | vendors | vendor > device > interface | 3,427 vendors, 20,537 devices; no interface lines in the real file |
| `C` | classes | class > subclass > protocol | 26, 48, 67 |
| `AT` | audio terminal types | one | 56 |
| `HID` | HID descriptor types | one | 3 |
| `R` | HID item types | one | 27 |
| `BIAS` | physical descriptor biases | one | 5 |
| `PHY` | physical descriptor item types | one | 40 |
| `HUT` | HID usage pages and usages | page > usage | 29 pages, 1,140 usages |
| `L` | languages | language > dialect | 72, 90 |
| `HCC` | HID country codes (decimal ids) | one | 36 |
| `VT` | video terminal types | one | 12 |

The parser (`primarysource/usbids/parse.py`) parses the whole real file with **0 unplaceable lines**. The Syntax
comments in the file are the specification; there is no other.

### USB-IF's document library (`https://www.usb.org/documents`)

- **No structured listing, no bulk download.** `https://www.usb.org/sitemap.xml` is 404. `/documents?_format=json`
  is 406. `/rss.xml` exists but is news and events, not documents. Individual files are served at
  `https://www.usb.org/sites/default/files/<name>` (PDFs, and ZIPs that hold a PDF plus adopters agreements).
- **The HTML listing is the structured source.** `/documents?items_per_page=200&page=N` returns 200 rows on page 0
  and 43 on page 1: **243 documents** on 2026-11-13. Each `<tr class="document-library__row">` already carries the
  file link with its type and byte length (`type="application/zip; length=9343367"`), the displayed file size, the
  title and the detail link `/document-library/<slug>`, and the Category, Type, Technology and Date columns. No
  detail page needs fetching to build a manifest: two requests list everything. (The footer's default is 50 per page
  and `page=0..4`; the 200 setting is one of the page's own options.)
- **robots.txt** (`https://www.usb.org/robots.txt`, 2026-11-13) disallows `/admin/`, `/search/`, `/user/...` and
  the Drupal core paths; `/documents` and `/sites/default/files/` are allowed, and no crawl delay is stated.
- **Terms.** There is no terms-of-use page: `/terms`, `/terms-of-use` and `/legal` are 404, and the footer's only
  legal link is the Privacy Statement (`/about/privacy-statement`) plus the trademark line "USB4, USB Type-C and
  USB-C are registered trademarks of USB Implementers Forum". The listing page carries a warranty disclaimer
  ("AS IS" and without warranty), nothing granting a licence. **The terms are inside each specification's own
  front matter.** Read locally in the usblib corpus (measured by searching its extracted text; none is reproduced
  here): 58 of the 102 documents carry an "Intellectual Property Disclaimer" or a "limited copyright license" or
  both, and 44 carry neither phrase. Six state the limited licence (eUSB2 v2, Power Delivery, Type-C cable and
  connector, UCSI, Type-C port controller interface, USB4 v2.0): it permits use and reproduction of the
  specification for the sole purpose of evaluating whether to implement it, grants no patent licence and no other
  right, and requires a separate agreement for more. The disclaimer, in Power Delivery for one, says the
  specification is provided "as is" and conveys no licence, express or implied. That is a licence to *evaluate*,
  not to *redistribute*.
  The right reading for the collection is the one `AGENTS.md` already holds: **volume only, never a layer, no text
  in the tree.**
- **Adopters agreements** ship inside the ZIPs; usblib excluded them from its index, correctly.

### USB-IF's vendor ID list

Published, as a **PDF**: `https://www.usb.org/sites/default/files/vendor_ids10282026.pdf` (2,123,987 bytes,
`Last-Modified: Thu, 29 Oct 2026 21:08:22 GMT`), linked from `https://www.usb.org/developers` where it is described
as a list of companies "to which USB-IF has assigned each Vendor ID in decimal format" and updated quarterly; a
second PDF lists obsolete vendor ids (`obsoletevids_10232019.pdf`). The filename carries the date (`MMDDYYYY`), so
the URL changes each quarter and must be discovered from the `/developers` page. `pdftotext -layout` gives a
two-column table (company, decimal id) of 14,382 lines; a rough pass finds about 13,880 rows and 13,878 distinct
ids, of which about 3,267 are among usb.ids' 3,427 vendors. **USB-IF's list is about four times the size of
usb.ids' vendor list** and the authoritative one for who owns a vendor id (the page says "Unauthorized use of
assigned or unassigned USB Vendor ID Numbers is strictly prohibited"). It names companies only, no products. No
licence is stated on the page or in the PDF's text; `/getting-vendor-id` describes buying an id
(US$6,000, or US$5,000 USB-IF membership, which includes one) and says nothing of reuse of the list. Treat as
volume only. Not built in this pass (below).

## What was built

`primarysource/usbids/`, standard library only:

| File | Role |
| --- | --- |
| `parse.py` | `parse(bytes, Limits)`, `parse_ref`, `format_ref`; 8 MB, 200,000 line, 512 character and 200,000 entry ceilings; NUL refused; a bad line is a `Problem`, never an entry |
| `importer.py` | pinned fetch behind an injected transport; `PIN`, `SOURCES`, `import_usbids`, `python -m primarysource.usbids.importer` |
| `store.py` | `$PRIMARYSOURCE_HOME/usbids/{usb.ids,manifest.json}`, parse cache, digest check on read |
| `tools.py` | `lookup`, `search`, `classify`, `sections` |
| `server.py`, `cli.py` | the MCP server (`usbids_` tools) and `primarysource usbids ...` |
| `__init__.py` | `COLLECTION` |

**Refs.** `usbids:1d6b` (vendor), `usbids:1d6b:0002` (device), `usbids:1d6b:0002:00` (interface, none exist in the
file today), `usbids:class/09`, `usbids:class/09/00/02`, `usbids:hut/01/006`, and `at/`, `hid/`, `item/`, `bias/`,
`phy/`, `lang/`, `hcc/`, `vt/`. Lower-cased on parse; `usbids:` is optional; a malformed one is a `LibError` with a
hint. Every entry is one line, so `¶n` is unused and a result's `unit` is `line`.

**Import.** One request to `https://usb-ids.gowdy.us/usb.ids`, falling back to the GitHub raw URL (waiting out the
one-second interval first; an interval under 1.0 is refused). Conditional (`If-None-Match`, `If-Modified-Since`)
after the first run, no redirects, https only, a source list the default transport enforces, an 8 MB ceiling,
`PRIMARYSOURCE_READONLY` honoured. The file is checked before anything is written: it must parse with entries and
**no** unplaceable line. The pin is `2026.06.26`, 730,605 bytes, sha256 above. A body with the pinned digest
installs. A different snapshot installs only with `--latest` (or `--sha256 <digest>`), because the file changes
and a pin is a statement about one day. The pinned version with different bytes is refused as altered. Bytes are
stored as served, atomically; `manifest.json` records url, sha256, size, version, date, fetch time, validators,
whether it was the pinned snapshot, the licence and counts.

**Placement.** Licence permits redistribution, so this is the one USB collection that may be a **layer** in a
built image (take the BSD-3-Clause option; keep the page's statement and the file header with the file, and the
manifest's `licence` field). A volume works the same way. Recommend layer, pinned at `PIN`.

**Real import (2026-11-13, scratch)** into
`D:\temp\claude\f40aa9f3f334cc70\4ca44696-6b0c-4e6c-a934-632927185025\scratchpad\usbids\`: one fetch, sha256 matched
the pin, 0 unparsed lines, 1 Latin-1 line, 25,615 entries: 3,427 vendors, 20,537 devices, 26 classes, 48 subclasses,
67 protocols, 56 audio terminal types, 3 HID descriptor types, 27 item types, 5 biases, 40 physical item types,
29 usage pages, 1,140 usages, 72 languages, 90 dialects, 36 country codes, 12 video terminal types. A second run sent
the conditional request and got 304.

## For the coordinator

BUILTIN line (`primarysource/registry.py`):

    "usbids": "primarysource.usbids:COLLECTION",

Extra (`pyproject.toml`, beside `nist = []` and `usb = []`):

    usbids = []

No exclusion is needed: `primarysource/usbids` and its tests are ruff- and mypy-clean under the project's own
rules, so do not add them to `extend-exclude` or the mypy `exclude`. The existing `mcp.*` override covers the
server's imports.

`ROADMAP.md` rows, status as measured:

| Row | Status |
| --- | --- |
| `ui.parse`: every section of `usb.ids` parses, hostile input is bounded | `[ok]` `tests/test_usbids_parse.py::test_every_section_and_level_is_parsed_with_its_header`, `::test_hostile_bytes_are_refused_or_confined`, `::test_a_line_that_cannot_be_placed_is_a_problem_not_an_entry` |
| `ui.refs`: `usbids:` refs round-trip and hostile refs are refused | `[ok]` `::test_refs_parse_and_format_round_trip`, `::test_a_string_that_names_nothing_is_refused_with_a_hint` |
| `ui.import_pinned`: pinned digest installs; other snapshots need `--latest` | `[ok]` `tests/test_usbids_importer.py::test_the_pinned_snapshot_installs_exactly_as_served_with_a_manifest`, `::test_an_unpinned_snapshot_needs_latest_or_its_digest`, `::test_the_pinned_version_with_other_bytes_is_refused_as_altered` |
| `ui.import_polite`: conditional, one request per second, https only | `[ok]` `::test_a_second_import_is_conditional_and_a_304_changes_nothing`, `::test_a_failing_first_source_falls_back_to_the_second_after_the_interval`, `::test_the_interval_is_never_under_one_second`, `::test_only_https_sources_are_accepted` |
| `ui.tools`: lookup, search, classify, sections, command, server | `[ok]` `tests/test_usbids_tools.py` (the server test skips without `mcp`) |
| `ui.real_file`: the real file parses with no problem | `[part]` verified once by hand (counts above); no test reads it, because the file is not in the tree. A CI job could run the importer into a temp home |
| `ui.multi_collection`: serve `usbids` beside `usb` in one process | `[ ]` waits on `cl.multi_collection_server` |
| `ui.vendor_list`: USB-IF's vendor ID PDF as a second table | `[ ]` needs a PDF reader (`pdftotext` as the usb collection uses, or pypdf), discovery of the dated URL from `/developers`, and a decision on licence (volume only). About four times usb.ids' vendors |
| `ui.core_grammar`: `Collection.grammar` is the real entry-keyed parser (`RefParser`, core b360a31) | `[ok]` `tests/test_usbids_parse.py::test_the_collection_grammar_is_the_real_parser` |
| `ui.search_index`: search is a linear scan over 25,615 entries per call | `[part]` fast enough today; an index would help a shared server |
| `ui.sibling_xref`: link `usbids:class/09` to the `usb` spec that defines the hub class | `[ ]` waits on the usb ref scheme |

Core observations: `RefGrammar` is `<doc>§<section>[#anchor][¶n]` and a database keyed by id has no sections, so
`COLLECTION.grammar` is `usbids.UsbidsRefs`, which wraps `usbids.parse.parse_ref` and `format_ref` (doc `usbids`, the
entry's ids as the section). `render.FOOTER_ORDER` was enough as it is.

## Proposals for primarysource.usb

Nothing in `primarysource/usb/`, the core, `PLAN.md` or `ROADMAP.md` was touched. These are findings for the
session that owns `usb`.

1. **Rebuild the 102-document corpus from a catalogue, reproducibly, in two requests plus the downloads.**
   The listing already contains each file's URL and byte length, so the discovery crawl in usblib's
   `discover_usb.py` (one request per page, then detail pages) can be replaced by:
   `GET https://www.usb.org/documents?items_per_page=200&page=0` and `page=1`, parse every
   `tr.document-library__row` with `html.parser` (no dependency), record per row: title, `/document-library/<slug>`,
   file URL, the `length=` bytes, the displayed size, category, type, technology, date. Write that as
   `$PRIMARYSOURCE_HOME/usb/listing.json` (243 rows on 2026-11-13) with the retrieval date. Then download each wanted
   file at no more than one request per second, record its sha256 beside the row, and **pin by sha256 and length,
   not by URL**: files are replaced in place under the same name (the PD zip carries date 11/05/2026 on a page whose
   slug is the unversioned `usb-power-delivery`). Selection (the 243 -> 102 step) stays `OVERRIDES` plus
   `usb-pdf-choice.json`; make that a data file with the reason for each choice, which is usblib brief U2.
   `robots.txt` allows both paths. A test with an injected transport and a saved page of invented rows covers it;
   do not save a real page (it is 435,977 bytes of USB-IF's HTML).
2. **Record `redistribute = volume`** for every document, with the reason: no terms page exists; the licence is the
   per-document front matter, which grants evaluation only. Cite the split from the usblib corpus (6 state the
   limited licence, 58 carry a licence or disclaimer notice, 44 carry neither phrase) and state that it was measured by
   searching the extracted text, so the 44 need a human look. Do not infer a grant from the disclaimer.
3. **USB-IF's own small tables are a better source than a PDF for some questions**, as HTML: `/defined-class-codes`
   (base class table, "Last Update: Septmeber 22, 2023" as spelled on the page), `/bos-descriptor-types`, and the
   HID information pages under Developers. They are the primary source for the class codes that usb.ids copies, and
   disagree with it: the class page lists 00h, 01h-03h, 05h-0Fh, 10h-14h, 3Ch, DCh, E0h, EFh, FEh, FFh, which usb.ids
   matches except that usb.ids adds `C 58 Xbox`, which is not USB-IF's. A `usb` cross-check would be one test.
4. **Vendor ID list** (`ui.vendor_list` above): either collection could own it; it belongs in `usbids` (it is an
   id table, not a specification) so `usb` should only link to it.
5. **Shape of a ref for `usb`**: usblib's `<number> §<section>` carries the revision inside the number string. The
   listing shows the real identity is slug plus date plus sha256; a ref that survives a re-issue needs
   `usb:<slug>@<sha256 prefix>§<section>` or a pinned `doc_id`. Decide this with the pinned-digest row.
6. **Duplicates and strays** the listing explains: usblib's 103 PDFs against 102 texts (a stray
   `DWG_Smart-Card_CCID_Rev110.pdf`) is a ZIP-versus-loose-PDF choice, which `listing.json` makes visible per row.
