# `ecma`: Ecma International standards, starting with ECMA-427

```
pip install "primarysource[ecma]"                 # pypdf, needed only to import; add ,mcp to serve it
primarysource ecma import 427                     # fetches the PDF from ecma-international.org (one request)
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
(`cite:`, `unit: sentence`, `span:`), `ecma_docs()`. The CLI has the same, plus `import [NUMBER] [--edition N]
[--file PDF]`; `--file` takes a PDF you downloaded yourself, checked against the same sha256.

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

## 7. Open

See the `ecma.*` roadmap rows in the coordinator's report: Ecmarkup source from `Ecma-TC54/ECMA-427`, other Ecma
standards, a layer placement decision, and table extraction.
