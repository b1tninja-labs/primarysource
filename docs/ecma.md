# `ecma`: Ecma International standards, starting with ECMA-427

```
pip install "primarysource[ecma]"                 # pypdf, needed only to import; add ,mcp to serve it
primarysource ecma fetch                          # the standards index and the withdrawn list it links to
primarysource ecma sync                           # import every pinned edition whose page still serves that PDF
primarysource ecma import 427                     # one pinned standard (or a PDF you already have, with --file)
primarysource ecma read "ecma:427§5.3¶2"
primarysource mcp --collection ecma               # tools ecma_read, ecma_search, ecma_outline, ecma_cite, ecma_docs
```

The repository holds **no Ecma text**: the code, `catalogue.json` and invented test PDFs. The PDF and its extraction
live under `$PRIMARYSOURCE_HOME/ecma/`.

## 1. Source, licence, placement

- **ECMA-427, Package-URL (PURL) specification, 1st edition, December 2025.** Landing page
  <https://ecma-international.org/publications-and-standards/standards/ecma-427/>; PDF
  `.../wp-content/uploads/ECMA-427_1st_edition_december_2025.pdf`, 2,320,437 bytes, 40 pages, sha256
  `037180df99e7d7c26d910dc3adb3fa07c4fb787cc4bd29e43634de3802313825`. This is the standard the owner named (purl,
  December 2025) for pkgformats and pkgtrust. The PDF's own bookmarks give 80 sections; the standard is authored
  in Ecmarkup on GitHub (`Ecma-TC54/ECMA-427`), a structured source that was not examined (roadmap row).
- **Licence.** The notice on page 6 of the PDF, read 2026-11-12, together with Ecma's text copyright policy
  (<https://ecma-international.org/policies/by-ipr/ecma-text-copyright-policy/>): the document may be copied,
  published and distributed, in whole or in part, provided the copyright notice and licence are on every copy; the
  only permitted derivative works are commentary or annotation, accessibility features, translations into other
  languages or formats, and implementations in conforming products; the content itself may not otherwise be
  modified; the English version on Ecma's site is the official one. Software in the standard is under the BSD
  licence printed in its last pages (a "Software License" section). The standard's page itself states no licence.
- **Placement: volume.** The notice would allow whole copies carrying the notice, but the extraction here is a
  derivative in a different form, Ecma asks that the standard be downloaded from its site, and the owner's research
  summary said "volume until read". The importer downloads from Ecma to the user's home; nothing is baked into an
  image. Moving to a layer would need the notice kept on every copy and a decision that the extraction counts as a
  format change.
- **ECMA-35, Character code structure and extension techniques, 6th edition, December 1994.** Landing page
  <https://ecma-international.org/publications-and-standards/standards/ecma-35/> (read 2026-11-21). PDF
  `.../wp-content/uploads/ECMA-35_6th_edition_december_1994.pdf`, 303,826 bytes, sha256
  `cd812a506f93bf44e0e6058fe423144c4dea8a64fbc96589cf99bcbe32fc1bf4`. The page states that this edition is
  fully identical with ISO/IEC 2022:1994. That designation is recorded on the catalogue edition (`identical`),
  and the ISO tools name `ecma:35@6` when 2022 is asked for and is not in the ISO library. The citation and
  `ecma_docs` say the same. An ISO number in the page's classification, without that statement, is not recorded.
- **ECMA-119, Volume and file structure of CD-ROM for information interchange, 5th edition, December 2024.**
  Landing page <https://ecma-international.org/publications-and-standards/standards/ecma-119/> (read 2026-11-17),
  which presents the 6th edition, December 2025, as the current document and still links the 5th. PDF
  `.../wp-content/uploads/ECMA-119_5th_edition_december_2024.pdf`, 2,230,005 bytes, 88 pages, sha256
  `60c83ce438ac1c367b82ecf60d8e0ac9d54b40843d62c1f19b80700dc4c19389`. Imported 2026-11-17: 254 sections,
  `pypdf` 6.12.2 (`pdftotext` was not on PATH). The 5th edition's introduction says that edition was developed
  to be technically identical with ISO/IEC 9660:2023. The 6th edition PDF is on the same page and was not
  imported: its body was not compared with the 5th. `iso9660` cites clauses from this import. The same
  catalogue terms apply: the PDF stays on the user's volume.
- **ECMA-167, Volume and file structure for write-once and rewritable media using non-sequential recording
  for information interchange, 3rd edition, June 1997.** Landing page
  <https://ecma-international.org/publications-and-standards/standards/ecma-167/> (read 2026-11-17), which
  presents that edition as current. PDF
  `.../wp-content/uploads/ECMA-167_3rd_edition_june_1997.pdf`, 579,302 bytes, 150 pages, sha256
  `6efe0f591e21da2b17288076b2653dc616800bdc94f83e74acba9279c84c34b7`. Imported 2026-11-17: 400 sections,
  `pypdf` 6.12.2 (`pdftotext` was not on PATH). `udfvol` cites clauses from this import. The PDF stays on
  the user's volume.

## 2. Refs

```
ecma:427§5.3¶2        ECMA-427@1§A        427§contributing-to-this-specification
```

`ecma:` is optional and `ECMA-427` means `427`. `@1` names the edition (without it, the highest imported).
`§` is a clause number **as the PDF's bookmarks give it**: `5.3`, `6.8.1.3`, `A` for Annex A, or the slug of an
unnumbered bookmark (`introduction`, `bibliography`). `¶n` is the nth **sentence** of the span: the clause's own
text, then each subsection as a `§5.3.1 Title` line and its text; a PDF gives sentences, not paragraphs. No `§`:
the whole standard. Bullets are sentences of their own (`•` kept).

## 3. Tools and commands

`ecma_read(ref, start, max_tokens)`, `ecma_search(query, doc, limit, start)` (sentences containing every word, else
at least half, flagged `relaxed:`), `ecma_outline(doc)` (clauses with refs and PDF pages), `ecma_cite(ref)`
(`cite:`, `unit: sentence`, `span:`), `ecma_docs()`. The CLI has the same, plus `fetch`, `sync [--only NUMBER]`
and `import [NUMBER] [--edition N] [--file PDF]`. `--file` takes a PDF you downloaded yourself, checked against
the same sha256. `sync` with no `--only` imports every pinned edition.

Captured 2026-11-17 from `ecma-international.org` (a browser HAR of the standards index; the standard page was
fetched again because that capture stored no body). The index is one
`ul.items-list-wrapper`: number, title, last change. It does not link a PDF. It does link
`/publications-and-standards/withdrawn-standards/`, and that page is the same kind of list. `fetch` stores both
as `remote.json` in the ecma home and downloads nothing else.

A standard's page carries the current edition in `p.ecma-item-edition` and one `a.download` outside
`ul.ecma-item-archives`. Older editions are the rows of that list. `sync` opens the page for each edition in
`catalogue.json`, and imports it only when that page still serves the pinned URL. An edition already stored
under the pin is skipped. A URL that has moved is an error and nothing is written. A standard the index lists
and the catalogue does not pin is not downloaded: the pin is the sha256 checked before the PDF is parsed.

## 4. The PDF reader is private, and a core change is proposed

`ecma/_pdf.py` reads a bookmarked PDF: the bookmarks come from `pypdf`; the page text from `pdftotext` when it is
on PATH (it keeps word spacing and puts headings where they are read), else from `pypdf` (content-stream order,
re-read in `layout` mode if fewer than 70% of the headings are found as lines). Page furniture (a line repeated on a
quarter of the pages, ignoring digits and Roman numerals) is dropped. It runs once at import and its result is stored
as JSON, so serving does not need `pypdf`. The bbf collection imports it too.

**Proposed core change:** promote `_pdf.py` to the core reader slots `cl.reader_pdf_pypdf` and
`cl.segment_bookmarks` (ROADMAP §2) with its tests (`tests/test_ecma.py`), keeping: the backend recorded in the
stored extraction and in the index source hash (PLAN §4), the `Section.anchor` the PLAN already wants, and the
bounds (64 MiB, 2,000 pages, 6,000 bookmarks). Nothing in the collection would change but an import line. The
same applies to the fetcher in `c2sp/_fetch.py` and `cl.fetch_pinned`.

ECMA-427 specifics seen: the PDF's headings are emitted out of order by the typesetter (Prince), so `pypdf`'s
default text puts a page's headings at the end; `pdftotext` and the `layout` fallback place them correctly.

## 5. What the importer distrusts

Only `https://ecma-international.org` and `www.ecma-international.org`, no credentials or ports, redirects only to
the same list, at most one request per second, a body over 64 MiB refused. The sha256 is checked before the PDF is
parsed; the file must start `%PDF-`; the PDF is extracted from a `.part` file and moved into place only if
extraction succeeds. A stored PDF or extraction that no longer matches (hash, JSON shape) is refused when read.

## 6. Real import (2026-11-13)

`primarysource ecma import 427`: one request, 80 sections (every one non-empty), 394 sentences, `pdftotext`
backend, well under a second. `ecma:427§5.3` is "Separator characters" (the brief's example).

`primarysource ecma import 119 --edition 5` (2026-11-17): one request, 254 sections, 88 pages, `pypdf`
backend. The stored PDF is `119-5.pdf` under the ecma home. ECMA-48, already imported in that home, was
left in place.

`primarysource ecma import 167 --edition 3` (2026-11-17): one request, 400 sections, 150 pages, `pypdf`
backend. The stored PDF is `167-3.pdf` under the ecma home.

## 7. Open

Ecmarkup source from `Ecma-TC54/ECMA-427` was not examined. Editions the index lists and `catalogue.json` does
not pin are not downloaded. A layer placement decision and table extraction are still open. Technical reports
are a separate archive and were not in the capture. The catalogue cannot hold one: a number is one to four
digits, and a standard page is parsed as the heading `ECMA-N` with a single current download. ECMA TR/112,
1st edition, December 2023, *Universal Disk Format (UDF) specification*, is eight part PDFs on
<https://ecma-international.org/publications-and-standards/technical-reports/ecma-tr-112/>
(`ECMA_TR-112-1` through `ECMA_TR-112-8`, each `..._1st_edition_december_2023.pdf`). No pin was invented.
`udfvol` leaves that revision as a note until a row needs one part.
