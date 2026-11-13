# iso: the owner's own purchased ISO publications

Recorded 2026-11-13. This document was asked for when the owner bought ISO standards as PDFs and asked where
official copies should go. It records:
- where the files go;
- why they stay out of every image;
- the licence decision;
- how the collection works.

```
pip install "primarysource[iso,mcp]"            # pypdf, needed only to import; mcp to serve
primarysource iso import                         # every new or changed PDF in purchased/
primarysource iso import my.pdf --designation "ISO/IEC 9899:2024"
primarysource iso search "integer promotion"
primarysource iso read "iso:9899@2024§6.3.1.1"
primarysource mcp --collection iso               # iso_read, iso_search, iso_outline, iso_cite, iso_docs
```

## 1. Where the files go

```
$PRIMARYSOURCE_HOME/iso/purchased/     # default: %LOCALAPPDATA%\primarysource\iso\purchased
```

- The folder exists on the owner's machine, with a README.
- It is the `iso` collection's home (`home.collection_home("iso")`), so the importer and index find it with
  no extra setting.
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
- **How it is served:** over stdio on the buyer's own machine, or with the iso home mounted read-only into the
  buyer's own container. It is never baked into an image or published.

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

- **Import** (`primarysource/iso/importer.py`). Each PDF is read once with `readers/pdf.py` and
  `readers/bookmarks.py` (ISO PDFs carry bookmarks) into `extracted/<key>.json`. Serving reads that file, so
  serving needs no `pypdf`.
  - `install.json` records the designation, the source path, sha256, size and mtime, and the extractor.
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
- **Tests** (`tests/test_iso.py`). They use an invented bookmarked PDF under ISO-store file names, never ISO
  text.

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
