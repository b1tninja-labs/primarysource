# iso: the owner's own purchased ISO publications

Recorded 2026-11-13. This document was asked for when the owner bought ISO standards as PDFs and asked where
official copies should go. It records:
- where the files go;
- why they stay out of every image;
- the licence decision;
- how the collection works.

```
pip install "primarysource[iso,mcp]"            # pypdf, needed only to import; mcp to serve
primarysource iso import                         # every new or changed PDF in the iso home
primarysource iso import my.pdf --designation "ISO/IEC 9899:2024"
primarysource iso search "integer promotion"
primarysource iso read "iso:9899@2024§6.3.1.1"
primarysource mcp --collection iso               # iso_read, iso_search, iso_outline, iso_cite, iso_docs
```

## 1. Where the files go

```
$PRIMARYSOURCE_ISO_HOME              # the owner's setting: M:\reference\iso
$PRIMARYSOURCE_HOME/iso              # otherwise
%LOCALAPPDATA%\primarysource\iso    # the default
```

- The PDFs go directly in the `iso` collection's home (`home.collection_home("iso")`); there is no subfolder.
  The import writes `extracted/`, `index.sqlite` and `install.json` beside them.
- `PRIMARYSOURCE_<NAME>_HOME` moves one collection anywhere (another drive, a mounted volume) while the others
  stay where they are, in the same order of precedence as the per-collection settings (`settings.py`).
- On the owner's machine the PDFs live in `M:\reference\iso`, set once as a user environment variable:
  `setx PRIMARYSOURCE_ISO_HOME M:\reference\iso`.
- A file named as the ISO store names it (`ISO_IEC_9899_2024(en).pdf`) is imported by `primarysource iso import`
  with no arguments. Any other name needs `--designation` with the designation printed on the cover.
- Put one PDF per publication there, exactly as delivered (watermarked in the buyer's name).
- Never put the files in this repository. `.gitignore` already refuses `*.pdf`, and `AGENTS.md` forbids
  document text in the tree.

## 2. Placement: personal volume, never an image

- **Not an image layer.** A container image is a copy that gets pushed, pulled and cached, so it would
  distribute the text.
- **Not a shared server.** A shared HTTP server answering several clients is networking.
- **What ISO says:** its store and help pages describe purchased PDFs as **single-user**. One user may access
  them, and posting them to a shared server or intranet needs a multi-user arrangement through the national
  member body (ISO help articles 664356 and 376041, read 2026-11-13).
- **How it is served:** over stdio on the buyer's own machine, or in the buyer's own container with the iso
  home mounted read-only, for example `-v M:\reference\iso:/data/iso:ro -e PRIMARYSOURCE_ISO_HOME=/data/iso`.
- **The owner's container (asked 2026-11-13).** The owner wants the image to include the iso data. No
  Dockerfile exists here yet. When one is written:
  - the iso data enters through the read-only mount above, so it is indexed and served without being in any
    image layer;
  - the image that is pushed (GHCR, the MCP Registry) never contains it;
  - if the owner wants it baked in anyway, that is a separate, local-only build target whose tag is never
    pushed, because a pushed layer is a copy given to everyone who can pull it.

## 3. Licence: the owner's decision

- **What ISO's terms forbid:** its no-cost access agreement and its Online Browsing Platform terms forbid
  text and data mining, scraping, harvesting, and use in "training, development, or operation" of an AI or
  machine-learning system. ISO also opts out of statutory text-and-data-mining exceptions, including EU
  Directive 2019/790 Art. 4.
- **What was not read:** the agreement for a purchase is the End Customer Licence Agreement
  (`iso.org/terms-conditions-licence-agreement.html`), and its page returned 403 to an automated fetch on
  2026-11-13.
- **Decided by the owner, 2026-11-13:** the owner confirmed for the copies bought ("Licence allows it, build")
  that extracting, indexing and serving them to the owner's own agents is permitted.
  The collection was built on that confirmation. The confirmation covers the owner's own copies only. Anyone else
  using this collection must read the agreement for their own purchase.

## 3a. How the collection works

- **What the file is** (`primarysource/iso/identify.py`, core `primarysource/identify.py`). People keep
  downloads under any name, so the import reads the PDF itself. On an ISO cover the designation follows
  `Reference number`, and every later page repeats it as a running header. Those outweigh the file name.
  - A renamed file imports under its real designation.
  - A file named for the wrong standard is imported as what its cover says, with a note.
  - A PDF that another collection recognises is refused with that collection's command. An ITU-T
    Recommendation or a NIST publication dropped in the iso folder is the usual case.
  - `primarysource identify <pdf or folder>` asks every collection. iso, itu, nist, ecma and ieee802
    recognise their own designations. It reports each PDF's designation, the evidence, and the command that
    imports it.
- **Import** (`primarysource/iso/importer.py`). Each PDF is read once with `readers/pdf.py` into
  `extracted/<key>.json`. Serving reads that file, so serving needs no `pypdf`.
  - **Cutting into clauses.** A PDF is cut at its bookmarks when it has them. Older ISO editions have none
    (both 7816 PDFs the owner bought, 2005 and 2006), so those are cut at their numbered headings. That uses
    `pdftotext -layout` text and the shared splitter (`pdfcorpus/split.py`), which reads the contents page.
    Measured 2026-11-13: ISO/IEC 7816-3:2006 gives 113 clauses and ISO/IEC 7816-4:2005 gives 125, from
    clause 1 on.
  - A free joint edition named by the IEC sync record (`free-sync.json`), whose PDF has neither bookmarks nor
    numbered headings, is cut one section per page. Any other unbookmarked PDF is still refused. A zip of such
    an edition contributes its own PDF; other members stay where they are. `iso_docs` and the citation say
    `free joint publication`. When the cover's reference number prints a different year from the IEC record, a
    ref for either year reads that import. A ref that names one of these editions and is not imported yet names
    the file already on disk and the import command.
  - A distributor's tracking string printed before a heading (`` --`,``,`---1 Scope ``) is stripped.
  - When the PDF's title metadata is useless (`Microsoft Word - C038770e.doc`), the English title on the
    cover is used.
  - `install.json` records the designation, the source path, sha256, size and mtime, the extractor and the
    segmenter.
  - **The PDF is not copied**, and the buyer's watermark is not recorded.
  - A folder import skips a file whose size and mtime are unchanged, and names each file it cannot import.
  - Imports hold the collection's bulk lock.
- **Index** (`index.sqlite`). The core FTS5 index (`cl.index_fts5`), BM25 with clause titles weighted 4. It is
  rebuilt atomically after each import, or with `primarysource iso index`.
- **Refs.** `iso:<number>@<year>§<clause>¶n`, for example `iso:9899@2024§6.5.2¶3`.
  - An amendment is `27001@2022+amd1-2024`.
  - The year goes after `@` because `:` already means a line range in a ref.
  - A bare number means the newest imported year.
  - A printed designation, such as `ISO/IEC 9899:2024§6.5.2`, is accepted.
  - `¶n` counts sentences of the clause's span: its own text, then each subsection.
- **Tools.** `iso_read`, `iso_search`, `iso_outline`, `iso_cite` and `iso_docs`, all text with the fixed
  footer.
  - Errors carry `hint` (the tool to call) and `action` (the import or index command).
  - `iso_docs` says when a source PDF has changed since import, or is missing.
  - When an Ecma edition's own page states that the edition is fully identical with the standard asked for,
    the error names that `ecma:` ref. If the edition is already imported, `hint` is `ecma_read` of that ref;
    otherwise `action` is `primarysource ecma import`. A search whose whole query is that standard, year
    included, adds the same `same text:` line, after any hits. A bare number is left as a word search when it
    hits. `iso_docs` lists these editions as `same text`. The ISO number in an Ecma page's classification is
    not that statement, and is not recorded.
- **Tests** (`tests/test_iso.py`, `tests/test_identify.py`). They use invented PDFs, with and without
  bookmarks and with an ISO-style cover and running header. They never use ISO text.

## 4. Freely available ISO text, and bulk collections

Measured 2026-11-13:

- **Free JTC 1 standards.** About 300 ISO/IEC JTC 1 standards are available at no charge. The old ITTF page
  (`standards.iso.org/ittf/PubliclyAvailableStandards/`) is closed and now points to the ISO and IEC
  webstores. The no-cost terms above apply to them too, so they are not a corpus for this package either.
- **ISO Online Browsing Platform** and **ANSI's Incorporated by Reference portal.** Both are read-only
  viewers, with no download, print or copy. The ANSI portal covers ISO standards cited in US federal
  regulations. Neither is a source an importer may scrape.
- **Public.Resource.Org.** It posts standards incorporated by reference into US law, and *ASTM v.
  Public.Resource.Org* (D.C. Cir. 2023) held that noncommercial posting of incorporated standards is fair use.
  The ruling covers incorporated standards only, in the US only, and no ISO collection from it was found in
  this search.
- **Bulk unofficial dumps.** Copies of paid ISO standards on file-sharing sites or archives are infringing
  copies. They are not a source for this package, and nothing here looks for them.
